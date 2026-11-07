import Darwin
import Foundation
import Virtualization

/// Gives the guest internet access, and only internet access.
///
/// The guest agent asks for every outgoing TCP connection and every name
/// lookup over vsock. palvmd checks each destination against the
/// `EgressPolicy` and makes the connection itself, so nothing inside the
/// guest — not even root — can reach this Mac or its local network.
public final class EgressService: NSObject, VZVirtioSocketListenerDelegate {
    public let policy: EgressPolicy
    public let maxConnections: Int
    private let log: @Sendable (String) -> Void
    private let listener = VZVirtioSocketListener()
    private let lock = NSLock()
    private var active = 0

    public init(
        policy: EgressPolicy = EgressPolicy(),
        maxConnections: Int = 512,
        log: @escaping @Sendable (String) -> Void
    ) {
        self.policy = policy
        self.maxConnections = maxConnections
        self.log = log
        super.init()
        listener.delegate = self
    }

    public func attach(to device: VZVirtioSocketDevice) {
        device.setSocketListener(listener, forPort: GuestChannel.egressPort)
    }

    public func listener(
        _ listener: VZVirtioSocketListener,
        shouldAcceptNewConnection connection: VZVirtioSocketConnection,
        from socketDevice: VZVirtioSocketDevice
    ) -> Bool {
        // Keep our own descriptor so the connection object can be released.
        let descriptor = dup(connection.fileDescriptor)
        connection.close()
        guard descriptor >= 0 else { return false }
        Thread.detachNewThread { [self] in handle(descriptor) }
        return true
    }

    // MARK: Requests

    func handle(_ descriptor: Int32) {
        guard reserve() else {
            try? Sockets.writeMessage(ChannelReply.failure("too many connections"), to: descriptor)
            close(descriptor)
            return
        }
        Sockets.noSigPipe(descriptor)
        Sockets.setTimeout(15, on: descriptor)
        guard let request = try? Sockets.readMessage(EgressRequest.self, from: descriptor) else {
            finish(descriptor)
            return
        }
        switch request.op {
        case .connect:
            connect(request, over: descriptor)
        case .resolve:
            let addresses = resolve(request.name ?? "")
            let reply = addresses.isEmpty
                ? ChannelReply.failure("no public address")
                : ChannelReply(ok: true, addresses: addresses.map(\.description))
            try? Sockets.writeMessage(reply, to: descriptor)
            finish(descriptor)
        case .time:
            try? Sockets.writeMessage(ChannelReply(ok: true, epoch: Date().timeIntervalSince1970), to: descriptor)
            finish(descriptor)
        }
    }

    private func connect(_ request: EgressRequest, over descriptor: Int32) {
        guard let host = request.host, let address = IPAddress(host), let port = request.port, port > 0 else {
            try? Sockets.writeMessage(ChannelReply.failure("invalid destination"), to: descriptor)
            finish(descriptor)
            return
        }
        if case .deny(let reason) = policy.decide(address) {
            log("blocked guest connection to \(address):\(port) (\(reason))")
            try? Sockets.writeMessage(ChannelReply.failure("blocked: \(reason)"), to: descriptor)
            finish(descriptor)
            return
        }
        let remote: Int32
        do {
            remote = try Sockets.connectTCP(to: address, port: port, timeout: 15)
        } catch {
            try? Sockets.writeMessage(ChannelReply.failure("\(error)"), to: descriptor)
            finish(descriptor)
            return
        }
        guard (try? Sockets.writeMessage(ChannelReply.success, to: descriptor)) != nil else {
            close(remote)
            finish(descriptor)
            return
        }
        Sockets.clearTimeout(on: descriptor)
        Splice.run(descriptor, remote) { [self] in release() }
    }

    /// Public addresses for `name`; private answers are dropped.
    func resolve(_ name: String) -> [IPAddress] {
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")
        guard !name.isEmpty, name.count <= 253, name.unicodeScalars.allSatisfy(allowed.contains) else {
            return []
        }
        var hints = addrinfo()
        hints.ai_family = AF_UNSPEC
        hints.ai_socktype = SOCK_STREAM
        var list: UnsafeMutablePointer<addrinfo>?
        guard getaddrinfo(name, nil, &hints, &list) == 0, let first = list else { return [] }
        defer { freeaddrinfo(list) }

        var seen: [IPAddress] = []
        for entry in sequence(first: first, next: { $0.pointee.ai_next }) {
            guard let raw = entry.pointee.ai_addr, let address = IPAddress(sockaddr: raw) else { continue }
            if !seen.contains(address) { seen.append(address) }
        }
        let permitted = seen.filter { policy.decide($0).isAllowed }
        if permitted.isEmpty && !seen.isEmpty {
            log("refused to resolve \(name) for the guest: only non-public addresses")
        }
        return permitted
    }

    // MARK: Accounting

    private func reserve() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard active < maxConnections else { return false }
        active += 1
        return true
    }

    private func release() {
        lock.lock()
        active -= 1
        lock.unlock()
    }

    private func finish(_ descriptor: Int32) {
        close(descriptor)
        release()
    }
}
