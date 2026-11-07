import Darwin
import Foundation

/// Serves `ControlRequest`s on a Unix socket.
///
/// Connections are read on a background queue; the handler is always called
/// on the main queue, where the virtual machine lives.
public final class ControlServer {
    public typealias Handler = (ControlRequest, @escaping (ControlResponse) -> Void) -> Void

    private let path: String
    private let handler: Handler
    private let queue = DispatchQueue(label: "pal.control", attributes: .concurrent)
    private var descriptor: Int32 = -1
    private var source: DispatchSourceRead?

    public init(socketURL: URL, handler: @escaping Handler) {
        self.path = socketURL.path
        self.handler = handler
    }

    public func start() throws {
        try FileManager.default.createDirectory(
            at: URL(fileURLWithPath: path).deletingLastPathComponent(),
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        descriptor = try UnixSocket.listen(at: path)
        let source = DispatchSource.makeReadSource(fileDescriptor: descriptor, queue: queue)
        source.setEventHandler { [weak self] in self?.accept() }
        source.resume()
        self.source = source
    }

    public func stop() {
        source?.cancel()
        source = nil
        if descriptor >= 0 {
            close(descriptor)
            descriptor = -1
        }
        unlink(path)
    }

    private func accept() {
        let client = Darwin.accept(descriptor, nil, nil)
        guard client >= 0 else { return }
        queue.async { [handler] in
            var timeout = timeval(tv_sec: 10, tv_usec: 0)
            setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
            let response: (ControlResponse) -> Void = { response in
                if let data = try? ControlCoding.line(response) {
                    try? UnixSocket.writeAll(data, to: client)
                }
                close(client)
            }
            guard let line = try? UnixSocket.readLine(from: client),
                  let request = try? ControlCoding.decoder().decode(ControlRequest.self, from: line)
            else {
                response(ControlResponse(ok: false, error: "malformed request"))
                return
            }
            DispatchQueue.main.async { handler(request, response) }
        }
    }
}
