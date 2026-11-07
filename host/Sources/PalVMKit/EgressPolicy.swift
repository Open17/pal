import Foundation

/// Decides which addresses the guest may connect to.
///
/// The guest may reach the public internet and nothing else: not this Mac,
/// not the local network, not VPN or carrier-grade NAT ranges, and no
/// special-purpose, multicast, or reserved addresses. Every address of the
/// Mac's own interfaces is refused as well, which also covers a Mac that has
/// a public address of its own.
public struct EgressPolicy: Sendable {
    public enum Decision: Equatable, Sendable {
        case allow
        case deny(String)

        public var isAllowed: Bool { self == .allow }
    }

    private struct Range: Sendable {
        let network: [UInt8]
        let prefixLength: Int
        let reason: String
    }

    private static func v4(_ a: UInt8, _ b: UInt8, _ c: UInt8, _ d: UInt8, _ prefix: Int, _ reason: String) -> Range {
        Range(network: [a, b, c, d], prefixLength: prefix, reason: reason)
    }

    private static func v6(_ groups: [UInt16], _ prefix: Int, _ reason: String) -> Range {
        let padded = groups + [UInt16](repeating: 0, count: 8 - groups.count)
        return Range(network: padded.flatMap { [UInt8($0 >> 8), UInt8($0 & 0xFF)] }, prefixLength: prefix, reason: reason)
    }

    private static let blockedIPv4: [Range] = [
        v4(0, 0, 0, 0, 8, "unspecified"),
        v4(10, 0, 0, 0, 8, "private network"),
        v4(100, 64, 0, 0, 10, "shared address space (carrier NAT, VPN overlays)"),
        v4(127, 0, 0, 0, 8, "loopback"),
        v4(169, 254, 0, 0, 16, "link-local"),
        v4(172, 16, 0, 0, 12, "private network"),
        v4(192, 0, 0, 0, 24, "protocol assignments"),
        v4(192, 0, 2, 0, 24, "documentation"),
        v4(192, 88, 99, 0, 24, "relay anycast"),
        v4(192, 168, 0, 0, 16, "private network"),
        v4(198, 18, 0, 0, 15, "benchmarking"),
        v4(198, 51, 100, 0, 24, "documentation"),
        v4(203, 0, 113, 0, 24, "documentation"),
        v4(224, 0, 0, 0, 4, "multicast"),
        v4(240, 0, 0, 0, 4, "reserved"),
    ]

    private static let blockedIPv6: [Range] = [
        v6([], 128, "unspecified"),
        v6([0, 0, 0, 0, 0, 0, 0, 1], 128, "loopback"),
        v6([0x64, 0xFF9B, 1], 48, "local translation"),
        v6([0x100], 64, "discard"),
        v6([0x2001], 23, "protocol assignments"),
        v6([0x2001, 0xDB8], 32, "documentation"),
        v6([0xFC00], 7, "unique local (private network)"),
        v6([0xFE80], 10, "link-local"),
        v6([0xFEC0], 10, "site-local"),
        v6([0xFF00], 8, "multicast"),
    ]

    private let localAddresses: @Sendable () -> Set<IPAddress>

    public init(localAddresses: @escaping @Sendable () -> Set<IPAddress> = IPAddress.localInterfaceAddresses) {
        self.localAddresses = localAddresses
    }

    public func decide(_ address: IPAddress) -> Decision {
        if let embedded = address.embeddedIPv4 {
            return decide(embedded)
        }
        if localAddresses().contains(address) {
            return .deny("an address of this Mac")
        }
        let ranges = address.isIPv4 ? Self.blockedIPv4 : Self.blockedIPv6
        if let range = ranges.first(where: { address.matches($0.network, prefixLength: $0.prefixLength) }) {
            return .deny(range.reason)
        }
        // Only global unicast IPv6 (2000::/3) is reachable on the internet.
        if !address.isIPv4 && !address.matches([0x20] + [UInt8](repeating: 0, count: 15), prefixLength: 3) {
            return .deny("not a global address")
        }
        return .allow
    }
}
