import Darwin
import Foundation

/// Blocking socket helpers shared by the vsock services.
enum Sockets {
    /// Read one newline-terminated JSON object.
    static func readMessage<T: Decodable>(_ type: T.Type, from descriptor: Int32) throws -> T {
        let line = try UnixSocket.readLine(from: descriptor, limit: 16 * 1024)
        guard !line.isEmpty else { throw PalHostError.controlFailed("connection closed") }
        return try JSONDecoder().decode(T.self, from: line)
    }

    static func writeMessage<T: Encodable>(_ value: T, to descriptor: Int32) throws {
        var data = try JSONEncoder().encode(value)
        data.append(0x0A)
        try UnixSocket.writeAll(data, to: descriptor)
    }

    static func setTimeout(_ seconds: Int, on descriptor: Int32) {
        var timeout = timeval(tv_sec: seconds, tv_usec: 0)
        setsockopt(descriptor, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        setsockopt(descriptor, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
    }

    static func clearTimeout(on descriptor: Int32) {
        setTimeout(0, on: descriptor)
    }

    static func noSigPipe(_ descriptor: Int32) {
        var on: Int32 = 1
        setsockopt(descriptor, SOL_SOCKET, SO_NOSIGPIPE, &on, socklen_t(MemoryLayout<Int32>.size))
    }

    /// Connect to `address:port` over TCP, giving up after `timeout` seconds.
    static func connectTCP(to address: IPAddress, port: UInt16, timeout: Int32) throws -> Int32 {
        let family = address.isIPv4 ? AF_INET : AF_INET6
        let descriptor = socket(family, SOCK_STREAM, IPPROTO_TCP)
        guard descriptor >= 0 else { throw UnixSocket.posixError("socket") }
        noSigPipe(descriptor)
        let flags = fcntl(descriptor, F_GETFL)
        _ = fcntl(descriptor, F_SETFL, flags | O_NONBLOCK)

        var result: Int32
        if address.isIPv4 {
            var storage = sockaddr_in()
            storage.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            storage.sin_family = sa_family_t(AF_INET)
            storage.sin_port = port.bigEndian
            withUnsafeMutableBytes(of: &storage.sin_addr) { $0.copyBytes(from: address.bytes) }
            result = withUnsafePointer(to: &storage) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }
        } else {
            var storage = sockaddr_in6()
            storage.sin6_len = UInt8(MemoryLayout<sockaddr_in6>.size)
            storage.sin6_family = sa_family_t(AF_INET6)
            storage.sin6_port = port.bigEndian
            withUnsafeMutableBytes(of: &storage.sin6_addr) { $0.copyBytes(from: address.bytes) }
            result = withUnsafePointer(to: &storage) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in6>.size))
                }
            }
        }
        if result != 0 && errno != EINPROGRESS {
            let error = UnixSocket.posixError("connect")
            close(descriptor)
            throw error
        }
        if result != 0 {
            var poller = pollfd(fd: descriptor, events: Int16(POLLOUT), revents: 0)
            let ready = poll(&poller, 1, timeout * 1000)
            var socketError: Int32 = 0
            var length = socklen_t(MemoryLayout<Int32>.size)
            getsockopt(descriptor, SOL_SOCKET, SO_ERROR, &socketError, &length)
            guard ready == 1, socketError == 0 else {
                close(descriptor)
                let reason = ready == 1 ? String(cString: strerror(socketError)) : "timed out"
                throw PalHostError.controlFailed("connect: \(reason)")
            }
        }
        _ = fcntl(descriptor, F_SETFL, flags & ~O_NONBLOCK)
        return descriptor
    }

    /// Listen for TCP connections on 127.0.0.1 only.
    static func listenLoopback(port: UInt16) throws -> Int32 {
        let descriptor = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP)
        guard descriptor >= 0 else { throw UnixSocket.posixError("socket") }
        var on: Int32 = 1
        setsockopt(descriptor, SOL_SOCKET, SO_REUSEADDR, &on, socklen_t(MemoryLayout<Int32>.size))
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = port.bigEndian
        address.sin_addr.s_addr = inet_addr("127.0.0.1")
        let bound = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bound == 0, listen(descriptor, 64) == 0 else {
            let error = UnixSocket.posixError("listen on 127.0.0.1:\(port)")
            close(descriptor)
            throw error
        }
        return descriptor
    }
}

/// Copies bytes in both directions between two connected sockets, then
/// closes both. Each direction runs on its own thread.
enum Splice {
    static func run(_ first: Int32, _ second: Int32, completion: (@Sendable () -> Void)? = nil) {
        Sockets.noSigPipe(first)
        Sockets.noSigPipe(second)
        let group = DispatchGroup()
        for (source, destination) in [(first, second), (second, first)] {
            group.enter()
            Thread.detachNewThread {
                copy(from: source, to: destination)
                shutdown(destination, SHUT_WR)
                group.leave()
            }
        }
        group.notify(queue: .global()) {
            close(first)
            close(second)
            completion?()
        }
    }

    private static func copy(from source: Int32, to destination: Int32) {
        var buffer = [UInt8](repeating: 0, count: 64 * 1024)
        while true {
            let count = read(source, &buffer, buffer.count)
            guard count > 0 else { return }
            var offset = 0
            while offset < count {
                let written = buffer.withUnsafeBytes { write(destination, $0.baseAddress! + offset, count - offset) }
                guard written > 0 else { return }
                offset += written
            }
        }
    }
}
