import Darwin
import Foundation

/// Minimal blocking Unix domain socket helpers.
enum UnixSocket {
    static func address(for path: String) throws -> sockaddr_un {
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(path.utf8)
        let capacity = MemoryLayout.size(ofValue: address.sun_path)
        guard bytes.count < capacity else {
            throw PalHostError.controlFailed("socket path is too long: \(path)")
        }
        withUnsafeMutableBytes(of: &address.sun_path) { buffer in
            buffer.copyBytes(from: bytes)
            buffer[bytes.count] = 0
        }
        return address
    }

    static func listen(at path: String) throws -> Int32 {
        unlink(path)
        let descriptor = socket(AF_UNIX, SOCK_STREAM, 0)
        guard descriptor >= 0 else { throw posixError("socket") }
        var address = try address(for: path)
        let bound = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard bound == 0 else {
            close(descriptor)
            throw posixError("bind \(path)")
        }
        chmod(path, 0o600)
        guard Darwin.listen(descriptor, 16) == 0 else {
            close(descriptor)
            throw posixError("listen")
        }
        return descriptor
    }

    static func connect(to path: String) throws -> Int32 {
        let descriptor = socket(AF_UNIX, SOCK_STREAM, 0)
        guard descriptor >= 0 else { throw posixError("socket") }
        var address = try address(for: path)
        let connected = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard connected == 0 else {
            close(descriptor)
            throw posixError("connect")
        }
        return descriptor
    }

    static func writeAll(_ data: Data, to descriptor: Int32) throws {
        try data.withUnsafeBytes { buffer in
            var offset = 0
            while offset < buffer.count {
                let written = write(descriptor, buffer.baseAddress! + offset, buffer.count - offset)
                guard written > 0 else { throw posixError("write") }
                offset += written
            }
        }
    }

    /// Read up to and excluding the first newline.
    static func readLine(from descriptor: Int32, limit: Int = 1 << 20) throws -> Data {
        var line = Data()
        var byte: UInt8 = 0
        while line.count < limit {
            let count = read(descriptor, &byte, 1)
            if count < 0 { throw posixError("read") }
            if count == 0 || byte == 0x0A { break }
            line.append(byte)
        }
        return line
    }

    static func posixError(_ operation: String) -> PalHostError {
        .controlFailed("\(operation): \(String(cString: strerror(errno)))")
    }
}
