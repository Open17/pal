import Darwin
import Foundation

/// Talks to a running palvmd.
public struct ControlClient: Sendable {
    public let socketURL: URL

    public init(socketURL: URL) {
        self.socketURL = socketURL
    }

    public init(paths: PalPaths = PalPaths()) {
        self.socketURL = paths.controlSocket
    }

    public func send(_ request: ControlRequest) throws -> ControlResponse {
        let descriptor = try UnixSocket.connect(to: socketURL.path)
        defer { close(descriptor) }
        var timeout = timeval(tv_sec: 10, tv_usec: 0)
        setsockopt(descriptor, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        try UnixSocket.writeAll(ControlCoding.line(request), to: descriptor)
        let line = try UnixSocket.readLine(from: descriptor)
        guard !line.isEmpty else { throw PalHostError.controlFailed("empty response") }
        return try ControlCoding.decoder().decode(ControlResponse.self, from: line)
    }

    /// The VM's status, or `nil` when palvmd is not running.
    public func status() -> ControlResponse? {
        try? send(ControlRequest(.status))
    }
}
