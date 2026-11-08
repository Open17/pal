import Foundation

/// The vsock channel between palvmd and the guest agent.
///
/// The guest has no network interface. Everything crosses this channel, and
/// each connection starts with one JSON line from the side that opened it and
/// one JSON line in reply, after which the connection carries raw bytes.
public enum GuestChannel {
    /// The guest agent listens here; palvmd connects to reach guest services.
    public static let inboundPort: UInt32 = 1025
    /// palvmd listens here; the guest agent connects to reach the internet.
    public static let egressPort: UInt32 = 1026
}

/// Sent by the guest on the egress port.
struct EgressRequest: Codable, Equatable {
    enum Operation: String, Codable {
        /// Open a TCP connection to `host:port` (an IP literal).
        case connect
        /// Resolve `name` to public addresses.
        case resolve
        /// Report the host's clock.
        case time
    }

    var op: Operation
    var host: String?
    var port: UInt16?
    var name: String?
}

/// Sent by palvmd on the inbound port.
struct InboundRequest: Codable, Equatable {
    var port: UInt16
}

struct ChannelReply: Codable, Equatable {
    var ok: Bool
    var error: String?
    var addresses: [String]?
    var epoch: Double?

    static let success = ChannelReply(ok: true)
    static func failure(_ reason: String) -> ChannelReply { ChannelReply(ok: false, error: reason) }
}

/// A guest TCP port made reachable on the Mac's loopback interface.
public struct PortForward: Codable, Equatable, Sendable {
    public var name: String
    public var hostPort: UInt16
    public var guestPort: UInt16

    public init(name: String, hostPort: UInt16, guestPort: UInt16) {
        self.name = name
        self.hostPort = hostPort
        self.guestPort = guestPort
    }

    /// SSH, the runtime API, the operator and shared-browser displays, and
    /// sixteen bot displays.
    public static let defaults: [PortForward] =
        [
            PortForward(name: "ssh", hostPort: 52022, guestPort: 22),
            PortForward(name: "api", hostPort: 8765, guestPort: 8765),
            PortForward(name: "vnc-operator", hostPort: 5901, guestPort: 5901),
            PortForward(name: "vnc-browser", hostPort: 5902, guestPort: 5902),
        ] + (10...25).map { PortForward(name: "vnc-\($0)", hostPort: UInt16(5900 + $0), guestPort: UInt16(5900 + $0)) }
}
