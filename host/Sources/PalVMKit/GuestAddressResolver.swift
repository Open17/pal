import Foundation

/// Finds the guest's IP address from the host's DHCP lease database.
///
/// The NAT network hands out addresses with the system DHCP server, which
/// records leases in `/var/db/dhcpd_leases`. Leases store MAC octets without
/// leading zeros (`2:a:3b:...`), so addresses are compared numerically.
public struct GuestAddressResolver: Sendable {
    public static let defaultLeasesPath = "/var/db/dhcpd_leases"

    public let leasesPath: String

    public init(leasesPath: String = GuestAddressResolver.defaultLeasesPath) {
        self.leasesPath = leasesPath
    }

    public struct Lease: Equatable, Sendable {
        public let ipAddress: String
        public let hardwareAddress: [UInt8]
        public let expires: UInt64
    }

    public func address(for macAddress: String) -> String? {
        guard let contents = try? String(contentsOfFile: leasesPath, encoding: .utf8) else {
            return nil
        }
        return Self.address(for: macAddress, inLeases: contents)
    }

    public static func address(for macAddress: String, inLeases contents: String) -> String? {
        guard let wanted = parseMAC(macAddress) else { return nil }
        return parseLeases(contents)
            .filter { $0.hardwareAddress == wanted }
            .max { $0.expires < $1.expires }?
            .ipAddress
    }

    public static func parseLeases(_ contents: String) -> [Lease] {
        var leases: [Lease] = []
        var fields: [String: String] = [:]
        for rawLine in contents.split(whereSeparator: \.isNewline) {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if line == "{" {
                fields = [:]
            } else if line == "}" {
                if let ip = fields["ip_address"],
                   let hardware = fields["hw_address"],
                   let mac = parseMAC(hardware.split(separator: ",").last.map(String.init) ?? "") {
                    let expires = fields["lease"].flatMap { UInt64($0.dropFirst(2), radix: 16) } ?? 0
                    leases.append(Lease(ipAddress: ip, hardwareAddress: mac, expires: expires))
                }
            } else if let separator = line.firstIndex(of: "=") {
                fields[String(line[..<separator])] = String(line[line.index(after: separator)...])
            }
        }
        return leases
    }

    static func parseMAC(_ value: String) -> [UInt8]? {
        let octets = value.split(separator: ":").compactMap { UInt8($0, radix: 16) }
        return octets.count == 6 ? octets : nil
    }
}
