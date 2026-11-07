import Darwin
import Foundation

/// An IPv4 or IPv6 address as raw bytes.
public struct IPAddress: Hashable, Sendable, CustomStringConvertible {
    public let bytes: [UInt8]  // 4 bytes for IPv4, 16 for IPv6

    public init?(bytes: [UInt8]) {
        guard bytes.count == 4 || bytes.count == 16 else { return nil }
        self.bytes = bytes
    }

    /// Parse a literal such as `93.184.216.34` or `2606:2800:220:1::`.
    public init?(_ string: String) {
        var v4 = in_addr()
        if inet_pton(AF_INET, string, &v4) == 1 {
            self.bytes = withUnsafeBytes(of: &v4) { Array($0) }
            return
        }
        var v6 = in6_addr()
        if inet_pton(AF_INET6, string, &v6) == 1 {
            self.bytes = withUnsafeBytes(of: &v6) { Array($0) }
            return
        }
        return nil
    }

    public var isIPv4: Bool { bytes.count == 4 }

    public var description: String {
        var buffer = [CChar](repeating: 0, count: Int(INET6_ADDRSTRLEN))
        var raw = bytes
        let family = isIPv4 ? AF_INET : AF_INET6
        guard inet_ntop(family, &raw, &buffer, socklen_t(buffer.count)) != nil else { return "?" }
        return String(cString: buffer)
    }

    /// Whether the first `prefixLength` bits equal those of `network`.
    func matches(_ network: [UInt8], prefixLength: Int) -> Bool {
        guard network.count == bytes.count else { return false }
        var remaining = prefixLength
        for index in 0..<bytes.count where remaining > 0 {
            let bits = min(8, remaining)
            let mask = UInt8(truncatingIfNeeded: 0xFF << (8 - bits))
            if bytes[index] & mask != network[index] & mask { return false }
            remaining -= bits
        }
        return true
    }

    /// The IPv4 address embedded in an IPv4-mapped, NAT64, or 6to4 IPv6 address.
    var embeddedIPv4: IPAddress? {
        guard !isIPv4 else { return nil }
        if matches([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0xFF, 0xFF, 0, 0, 0, 0], prefixLength: 96)
            || matches([0, 0x64, 0xFF, 0x9B, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], prefixLength: 96) {
            return IPAddress(bytes: Array(bytes[12..<16]))
        }
        if matches([0x20, 0x02] + [UInt8](repeating: 0, count: 14), prefixLength: 16) {
            return IPAddress(bytes: Array(bytes[2..<6]))
        }
        return nil
    }

    /// Every address assigned to this Mac's network interfaces.
    public static func localInterfaceAddresses() -> Set<IPAddress> {
        var result: Set<IPAddress> = []
        var list: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&list) == 0, let first = list else { return result }
        defer { freeifaddrs(list) }
        for pointer in sequence(first: first, next: { $0.pointee.ifa_next }) {
            guard let address = pointer.pointee.ifa_addr else { continue }
            if let parsed = IPAddress(sockaddr: address) { result.insert(parsed) }
        }
        return result
    }

    init?(sockaddr address: UnsafePointer<sockaddr>) {
        switch Int32(address.pointee.sa_family) {
        case AF_INET:
            let bytes = address.withMemoryRebound(to: sockaddr_in.self, capacity: 1) {
                withUnsafeBytes(of: $0.pointee.sin_addr) { Array($0) }
            }
            self.init(bytes: bytes)
        case AF_INET6:
            let bytes = address.withMemoryRebound(to: sockaddr_in6.self, capacity: 1) {
                withUnsafeBytes(of: $0.pointee.sin6_addr) { Array($0) }
            }
            self.init(bytes: bytes)
        default:
            return nil
        }
    }
}
