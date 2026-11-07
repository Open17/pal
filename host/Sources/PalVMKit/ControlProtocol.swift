import Foundation

/// Requests and responses exchanged with palvmd over its control socket.
///
/// The wire format is one JSON object per line in each direction.
public struct ControlRequest: Codable, Equatable, Sendable {
    public enum Command: String, Codable, Sendable {
        /// Report the VM's state and address.
        case status
        /// Shut the guest down cleanly; palvmd exits once it has stopped.
        case stop
    }

    public var command: Command

    public init(_ command: Command) {
        self.command = command
    }
}

public struct ControlResponse: Codable, Equatable, Sendable {
    public var ok: Bool
    public var state: VirtualMachineHost.State?
    /// Guest services reachable on 127.0.0.1 of this Mac.
    public var forwardedPorts: [PortForward]?
    public var pid: Int32?
    public var startedAt: Date?
    public var error: String?

    public init(
        ok: Bool,
        state: VirtualMachineHost.State? = nil,
        forwardedPorts: [PortForward]? = nil,
        pid: Int32? = nil,
        startedAt: Date? = nil,
        error: String? = nil
    ) {
        self.ok = ok
        self.state = state
        self.forwardedPorts = forwardedPorts
        self.pid = pid
        self.startedAt = startedAt
        self.error = error
    }
}

enum ControlCoding {
    static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }

    static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    static func line<T: Encodable>(_ value: T) throws -> Data {
        var data = try encoder().encode(value)
        data.append(0x0A)
        return data
    }
}
