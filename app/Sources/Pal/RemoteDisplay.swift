import AppKit
import CommonCrypto
import Network

/// A small VNC (RFB 3.8) client for watching and controlling a display.
///
/// It asks for 32-bit true-colour pixels and the Raw and CopyRect encodings,
/// which is all a loopback connection needs, and supports desktop resizing.
/// Frames are delivered as `CGImage`s on the main queue, at most ~30 per second.
nonisolated final class RemoteDisplay: @unchecked Sendable {
    enum State: Equatable {
        case connecting, connected(name: String), failed(String), closed
    }

    var onState: (@MainActor @Sendable (State) -> Void)?
    var onFrame: (@MainActor @Sendable (CGImage) -> Void)?

    private let connection: NWConnection
    private let password: String
    private let queue = DispatchQueue(label: "pal.vnc")
    private let lock = NSLock()
    private var framebuffer: [UInt8] = []
    private(set) var width = 0
    private(set) var height = 0
    private var lastPublish = Date.distantPast
    private var publishPending = false
    private var buttons: UInt8 = 0

    init(port: Int, password: String) {
        self.password = password
        connection = NWConnection(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: UInt16(port))!, using: .tcp)
    }

    func start() {
        Task.detached { [self] in
            do {
                try await open()
                try await handshake()
                try await run()
            } catch {
                emit(.failed(Self.describe(error)))
            }
        }
    }

    func stop() {
        connection.cancel()
        emit(.closed)
    }

    // MARK: Input

    /// Move the pointer to `point` (framebuffer coordinates) with `buttons` held.
    func pointer(x: Int, y: Int, buttons mask: UInt8) {
        buttons = mask
        var message = Data([5, mask])
        message.append(UInt16(clamping: max(0, min(x, width - 1))).bigEndianData)
        message.append(UInt16(clamping: max(0, min(y, height - 1))).bigEndianData)
        send(message)
    }

    enum ScrollDirection {
        case up, down, left, right

        /// The wheel "buttons" VNC uses for each direction.
        var mask: UInt8 {
            switch self {
            case .up: 8
            case .down: 16
            case .left: 32
            case .right: 64
            }
        }
    }

    /// One notch of the scroll wheel.
    func scroll(x: Int, y: Int, _ direction: ScrollDirection) {
        pointer(x: x, y: y, buttons: buttons | direction.mask)
        pointer(x: x, y: y, buttons: buttons & ~direction.mask)
    }

    func key(_ keysym: UInt32, down: Bool) {
        var message = Data([4, down ? 1 : 0, 0, 0])
        message.append(keysym.bigEndianData)
        send(message)
    }

    // MARK: Protocol

    private func open() async throws {
        emit(.connecting)
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            // State updates arrive on `queue`, one at a time.
            final class Once: @unchecked Sendable { var done = false }
            let once = Once()
            connection.stateUpdateHandler = { state in
                guard !once.done else { return }
                switch state {
                case .ready:
                    once.done = true
                    continuation.resume()
                case .failed(let error), .waiting(let error):
                    once.done = true
                    continuation.resume(throwing: error)
                case .cancelled:
                    once.done = true
                    continuation.resume(throwing: RFBError.closed)
                default:
                    break
                }
            }
            connection.start(queue: queue)
        }
    }

    private func handshake() async throws {
        let version = try await read(12)
        guard String(decoding: version, as: UTF8.self).hasPrefix("RFB 003.") else { throw RFBError.protocolError("not a VNC server") }
        send(Data("RFB 003.008\n".utf8))

        let count = Int(try await read(1).first!)
        if count == 0 {
            let length = Int(try await read(4).bigEndianUInt32)
            throw RFBError.protocolError(String(decoding: try await read(length), as: UTF8.self))
        }
        let types = try await read(count)
        if types.contains(2) {
            send(Data([2]))
            let challenge = try await read(16)
            send(try Self.encrypt(challenge, password: password))
        } else if types.contains(1) {
            send(Data([1]))
        } else {
            throw RFBError.protocolError("no supported sign-in method")
        }
        let result = try await read(4).bigEndianUInt32
        guard result == 0 else { throw RFBError.protocolError("the display refused the password") }

        send(Data([1]))  // shared: don't disconnect other viewers
        let header = try await read(24)
        let nameLength = Int(header.subdata(in: 20..<24).bigEndianUInt32)
        let name = String(decoding: try await read(nameLength), as: UTF8.self)
        resize(Int(header.subdata(in: 0..<2).bigEndianUInt16), Int(header.subdata(in: 2..<4).bigEndianUInt16))

        // 32 bits per pixel, little-endian XRGB: B, G, R, X in memory.
        var format = Data([0, 0, 0, 0, 32, 24, 0, 1])
        format.append(UInt16(255).bigEndianData)
        format.append(UInt16(255).bigEndianData)
        format.append(UInt16(255).bigEndianData)
        format.append(contentsOf: [16, 8, 0, 0, 0, 0])
        send(format)

        let encodings: [Int32] = [1, 0, -223]  // CopyRect, Raw, DesktopSize
        var setEncodings = Data([2, 0])
        setEncodings.append(UInt16(encodings.count).bigEndianData)
        for encoding in encodings { setEncodings.append(UInt32(bitPattern: encoding).bigEndianData) }
        send(setEncodings)

        emit(.connected(name: name))
        requestUpdate(incremental: false)
    }

    private func run() async throws {
        while true {
            let type = try await read(1).first!
            switch type {
            case 0:
                try await readFramebufferUpdate()
                publish()
                requestUpdate(incremental: true)
            case 1:  // colour map entries; unused with true colour
                let header = try await read(5)
                _ = try await read(Int(header.subdata(in: 3..<5).bigEndianUInt16) * 6)
            case 2:  // bell
                break
            case 3:  // clipboard text; sharing is off, so discard it
                let header = try await read(7)
                _ = try await read(Int(header.subdata(in: 3..<7).bigEndianUInt32))
            default:
                throw RFBError.protocolError("unexpected message \(type)")
            }
        }
    }

    private func readFramebufferUpdate() async throws {
        let header = try await read(3)
        let rects = Int(header.subdata(in: 1..<3).bigEndianUInt16)
        for _ in 0..<rects {
            let r = try await read(12)
            let x = Int(r.subdata(in: 0..<2).bigEndianUInt16)
            let y = Int(r.subdata(in: 2..<4).bigEndianUInt16)
            let w = Int(r.subdata(in: 4..<6).bigEndianUInt16)
            let h = Int(r.subdata(in: 6..<8).bigEndianUInt16)
            let encoding = Int32(bitPattern: r.subdata(in: 8..<12).bigEndianUInt32)
            switch encoding {
            case 0:
                let pixels = try await read(w * h * 4)
                blit(pixels, x: x, y: y, w: w, h: h)
            case 1:
                let source = try await read(4)
                copy(fromX: Int(source.subdata(in: 0..<2).bigEndianUInt16), fromY: Int(source.subdata(in: 2..<4).bigEndianUInt16), x: x, y: y, w: w, h: h)
            case -223:
                resize(w, h)
            default:
                throw RFBError.protocolError("unsupported encoding \(encoding)")
            }
        }
    }

    private func requestUpdate(incremental: Bool) {
        var message = Data([3, incremental ? 1 : 0, 0, 0, 0, 0])
        message.append(UInt16(clamping: width).bigEndianData)
        message.append(UInt16(clamping: height).bigEndianData)
        send(message)
    }

    // MARK: Framebuffer

    private func resize(_ w: Int, _ h: Int) {
        lock.lock()
        width = w
        height = h
        framebuffer = [UInt8](repeating: 0, count: w * h * 4)
        lock.unlock()
    }

    private func blit(_ pixels: Data, x: Int, y: Int, w: Int, h: Int) {
        lock.lock()
        defer { lock.unlock() }
        guard x + w <= width, y + h <= height else { return }
        pixels.withUnsafeBytes { source in
            framebuffer.withUnsafeMutableBytes { target in
                for row in 0..<h {
                    let from = source.baseAddress! + row * w * 4
                    let to = target.baseAddress! + ((y + row) * width + x) * 4
                    memcpy(to, from, w * 4)
                }
            }
        }
    }

    private func copy(fromX: Int, fromY: Int, x: Int, y: Int, w: Int, h: Int) {
        lock.lock()
        defer { lock.unlock() }
        guard fromX + w <= width, fromY + h <= height, x + w <= width, y + h <= height else { return }
        let rows = Array(0..<h)
        // Copy in the direction that never overwrites rows still to be read.
        for row in (fromY < y ? rows.reversed() : rows) {
            let from = ((fromY + row) * width + fromX) * 4
            let to = ((y + row) * width + x) * 4
            _ = framebuffer.withUnsafeMutableBytes { buffer in
                memmove(buffer.baseAddress! + to, buffer.baseAddress! + from, w * 4)
            }
        }
    }

    /// Hand the current frame to the UI, at most about 30 times a second.
    private func publish() {
        let now = Date()
        let wait = 1.0 / 30 - now.timeIntervalSince(lastPublish)
        if wait > 0 {
            guard !publishPending else { return }
            publishPending = true
            queue.asyncAfter(deadline: .now() + wait) { [self] in
                publishPending = false
                publish()
            }
            return
        }
        lastPublish = now
        lock.lock()
        let data = Data(framebuffer)
        let (w, h) = (width, height)
        lock.unlock()
        guard w > 0, h > 0, let provider = CGDataProvider(data: data as CFData),
              let image = CGImage(
                  width: w, height: h, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: w * 4,
                  space: CGColorSpace(name: CGColorSpace.sRGB)!,
                  bitmapInfo: CGBitmapInfo(rawValue: CGBitmapInfo.byteOrder32Little.rawValue | CGImageAlphaInfo.noneSkipFirst.rawValue),
                  provider: provider, decode: nil, shouldInterpolate: true, intent: .defaultIntent
              )
        else { return }
        let onFrame = onFrame
        Task { @MainActor in onFrame?(image) }
    }

    // MARK: Plumbing

    private func read(_ count: Int) async throws -> Data {
        guard count > 0 else { return Data() }
        return try await withCheckedThrowingContinuation { continuation in
            connection.receive(minimumIncompleteLength: count, maximumLength: count) { data, _, _, error in
                if let error {
                    continuation.resume(throwing: error)
                } else if let data, data.count == count {
                    continuation.resume(returning: data)
                } else {
                    continuation.resume(throwing: RFBError.closed)
                }
            }
        }
    }

    private func send(_ data: Data) {
        connection.send(content: data, completion: .idempotent)
    }

    private func emit(_ state: State) {
        let onState = onState
        Task { @MainActor in onState?(state) }
    }

    /// VNC authentication: DES-encrypt the challenge with the password as the
    /// key, each key byte's bits reversed.
    static func encrypt(_ challenge: Data, password: String) throws -> Data {
        var key = [UInt8](repeating: 0, count: 8)
        for (i, byte) in password.utf8.prefix(8).enumerated() {
            var reversed: UInt8 = 0
            for bit in 0..<8 where byte & (1 << bit) != 0 { reversed |= 1 << (7 - bit) }
            key[i] = reversed
        }
        var output = [UInt8](repeating: 0, count: 16)
        var moved = 0
        let status = challenge.withUnsafeBytes { input in
            CCCrypt(
                CCOperation(kCCEncrypt), CCAlgorithm(kCCAlgorithmDES), CCOptions(kCCOptionECBMode),
                key, kCCKeySizeDES, nil, input.baseAddress, 16, &output, 16, &moved
            )
        }
        guard status == kCCSuccess else { throw RFBError.protocolError("could not answer the password challenge") }
        return Data(output)
    }

    private static func describe(_ error: any Error) -> String {
        if let error = error as? RFBError {
            switch error {
            case .closed: return "The display closed the connection."
            case .protocolError(let message): return message.prefix(1).uppercased() + message.dropFirst()
            }
        }
        if case NWError.posix(.ECONNREFUSED) = error { return "Nothing is answering on this display's port." }
        return error.localizedDescription
    }
}

nonisolated enum RFBError: Error {
    case closed
    case protocolError(String)
}

// MARK: - Keys

/// Maps Mac key events to X keysyms. Command acts as Control inside the VM,
/// so ⌘C and ⌘V do what you expect in Linux apps.
nonisolated enum KeySym {
    static let shift: UInt32 = 0xFFE1
    static let control: UInt32 = 0xFFE3
    static let command: UInt32 = 0xFFE4  // Control_R
    static let option: UInt32 = 0xFFE9

    private static let special: [UInt16: UInt32] = [
        36: 0xFF0D, 76: 0xFF8D, 48: 0xFF09, 51: 0xFF08, 117: 0xFFFF, 53: 0xFF1B,
        123: 0xFF51, 126: 0xFF52, 124: 0xFF53, 125: 0xFF54,
        115: 0xFF50, 119: 0xFF57, 116: 0xFF55, 121: 0xFF56,
        122: 0xFFBE, 120: 0xFFBF, 99: 0xFFC0, 118: 0xFFC1, 96: 0xFFC2, 97: 0xFFC3,
        98: 0xFFC4, 100: 0xFFC5, 101: 0xFFC6, 109: 0xFFC7, 103: 0xFFC8, 111: 0xFFC9,
    ]

    static func from(_ event: NSEvent) -> UInt32? {
        if let keysym = special[event.keyCode] { return keysym }
        let flags = event.modifierFlags
        let text = flags.contains(.command) || flags.contains(.control)
            ? event.charactersIgnoringModifiers
            : event.characters
        guard let scalar = text?.unicodeScalars.first else { return nil }
        let value = scalar.value
        // Latin-1 maps directly; everything else uses the Unicode keysym range.
        return value < 0x100 ? value : 0x0100_0000 | value
    }
}

// MARK: - Byte helpers

nonisolated extension FixedWidthInteger {
    var bigEndianData: Data {
        withUnsafeBytes(of: bigEndian) { Data($0) }
    }
}

nonisolated extension Data {
    var bigEndianUInt16: UInt16 { reduce(0) { $0 << 8 | UInt16($1) } }
    var bigEndianUInt32: UInt32 { reduce(0) { $0 << 8 | UInt32($1) } }
}
