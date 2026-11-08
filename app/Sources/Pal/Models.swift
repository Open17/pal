import Foundation

// Mirrors of the runtime's JSON shapes (runtime/src/pal/api). Keys arrive in
// snake_case and are converted by `JSONDecoder.pal()`.

/// A bot's state as the runtime reports it, plus "waiting on a teammate".
nonisolated enum PalStatus: Hashable, Sendable {
    case offline, idle, busy, error
    /// Ready, but Claude isn't signed in, so it can't answer.
    case signedOut
    case waiting(on: String)

    init(raw: String, waitingOn: String? = nil, signedIn: Bool = true) {
        if let waitingOn { self = .waiting(on: waitingOn); return }
        switch raw {
        case "idle": self = signedIn ? .idle : .signedOut
        case "busy": self = .busy
        case "error": self = .error
        default: self = .offline
        }
    }

    var isWorking: Bool {
        switch self {
        case .busy, .waiting: true
        default: false
        }
    }
}

/// A bot on the team (`GET /v1/bots`).
nonisolated struct Pal: Decodable, Identifiable, Hashable, Sendable {
    var id: String
    var name: String
    var role: String
    var color: String?
    var rawStatus: String
    var queued: Int
    var model: String
    var effort: String
    var sessionId: String?
    var lastError: String?
    var persona: String?
    /// Set from `bot.status` events while the bot waits on a teammate.
    var waitingOn: String?
    /// Whether Claude is signed in on Pal's computer; kept in step by `PalStore`.
    var signedIn = true

    var status: PalStatus { PalStatus(raw: rawStatus, waitingOn: waitingOn, signedIn: signedIn) }

    private enum CodingKeys: String, CodingKey {
        case id, name, role, color, queued, model, effort, sessionId, lastError, persona
        case rawStatus = "status"
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        role = try c.decodeIfPresent(String.self, forKey: .role) ?? ""
        color = try c.decodeIfPresent(String.self, forKey: .color)
        rawStatus = try c.decodeIfPresent(String.self, forKey: .rawStatus) ?? "offline"
        queued = try c.decodeIfPresent(Int.self, forKey: .queued) ?? 0
        model = try c.decode(String.self, forKey: .model)
        effort = try c.decode(String.self, forKey: .effort)
        sessionId = try c.decodeIfPresent(String.self, forKey: .sessionId)
        lastError = try c.decodeIfPresent(String.self, forKey: .lastError)
        persona = try c.decodeIfPresent(String.self, forKey: .persona)
    }
}

/// One message in a conversation between the user and a bot, or two bots.
nonisolated struct Message: Decodable, Identifiable, Hashable, Sendable {
    var id: String
    var sender: String
    var recipient: String
    var content: String
    /// chat, request, reply, or notice.
    var kind: String
    var replyTo: String?
    var metadata: [String: JSONValue]
    var createdAt: Date
    var conversationId: String

    var isError: Bool { metadata["error"] == .bool(true) }

    private enum CodingKeys: String, CodingKey {
        case id, sender, recipient, content, kind, replyTo, metadata, createdAt, conversationId
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        sender = try c.decode(String.self, forKey: .sender)
        recipient = try c.decode(String.self, forKey: .recipient)
        content = try c.decode(String.self, forKey: .content)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "chat"
        replyTo = try c.decodeIfPresent(String.self, forKey: .replyTo)
        metadata = try c.decodeIfPresent([String: JSONValue].self, forKey: .metadata) ?? [:]
        createdAt = try c.decode(Date.self, forKey: .createdAt)
        conversationId = try c.decodeIfPresent(String.self, forKey: .conversationId)
            ?? Message.conversationId(sender, recipient)
    }

    /// Matches the runtime: the user first, otherwise the two bots alphabetically.
    static func conversationId(_ a: String, _ b: String) -> String {
        if a == "user" { return "user--\(b)" }
        if b == "user" { return "user--\(a)" }
        return a < b ? "\(a)--\(b)" : "\(b)--\(a)"
    }
}

nonisolated struct ConversationSummary: Decodable, Identifiable, Hashable, Sendable {
    var id: String
    var participants: [String]
    var messageCount: Int
    var lastMessage: Message?

    var isBetweenBots: Bool { !participants.contains("user") }
}

/// A bot's (or the operator's) desktop.
nonisolated struct Display: Decodable, Identifiable, Hashable, Sendable {
    var owner: String
    var display: String
    var number: Int
    /// stopped, starting, running, sleeping, failed.
    var state: String
    var viewers: Int
    var vncPort: Int
    var error: String?

    var id: String { owner }
    var isLive: Bool { state == "running" || state == "sleeping" }
}

nonisolated struct MemoryEntry: Decodable, Identifiable, Hashable, Sendable {
    var id: String
    var title: String
    var description: String
    var kind: String
    var tags: [String]
    var author: String
    var createdAt: Date
    var updatedAt: Date
    var body: String
}

nonisolated struct AuthInfo: Decodable, Hashable, Sendable {
    var ok: Bool
    var method: String
    var detail: String
}

nonisolated struct RuntimeStatus: Decodable, Sendable {
    var version: String
    var auth: AuthInfo
    var bots: [Pal]
    var displays: [Display]
}

nonisolated struct ModelDefaults: Codable, Hashable, Sendable {
    var model: String
    var effort: String
}

nonisolated struct SettingsInfo: Decodable, Sendable {
    var defaults: ModelDefaults
    var effortLevels: [String]
}

// MARK: - Events

/// Live events from `GET /v1/events`.
nonisolated enum ServerEvent: Decodable, Sendable {
    case hello
    case messageCreated(Message)
    case botStatus(bot: String, status: String, queued: Int, waitingOn: String?)
    case textDelta(bot: String, text: String)
    case thinking(bot: String, text: String)
    case toolStarted(bot: String, toolUseId: String, tool: String, input: JSONValue)
    case toolFinished(bot: String, toolUseId: String, isError: Bool)
    case turnCompleted(bot: String, messageId: String?)
    case settingsChanged(bot: String, model: String, effort: String)
    case botAdded(String)
    /// A bot's name, role, instructions, or color changed.
    case botUpdated(Pal)
    case botRemoved(String)
    case display(Display)
    case unknown

    private enum K: String, CodingKey { case type, data }
    private enum D: String, CodingKey {
        case message, bot, status, queued, waitingOn, text, toolUseId, tool, input, isError
        case messageId, model, effort, display
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: K.self)
        let type = try c.decode(String.self, forKey: .type)
        guard type != "hello" else { self = .hello; return }
        let d = try c.nestedContainer(keyedBy: D.self, forKey: .data)
        let bot = { try d.decode(String.self, forKey: .bot) }
        switch type {
        case "message.created":
            self = .messageCreated(try d.decode(Message.self, forKey: .message))
        case "bot.status":
            self = .botStatus(
                bot: try bot(),
                status: try d.decode(String.self, forKey: .status),
                queued: try d.decodeIfPresent(Int.self, forKey: .queued) ?? 0,
                waitingOn: try d.decodeIfPresent(String.self, forKey: .waitingOn)
            )
        case "bot.text.delta":
            self = .textDelta(bot: try bot(), text: try d.decode(String.self, forKey: .text))
        case "bot.thinking":
            self = .thinking(bot: try bot(), text: try d.decode(String.self, forKey: .text))
        case "bot.tool.started":
            self = .toolStarted(
                bot: try bot(),
                toolUseId: try d.decode(String.self, forKey: .toolUseId),
                tool: try d.decode(String.self, forKey: .tool),
                input: (try? d.decode(JSONValue.self, forKey: .input)) ?? .null
            )
        case "bot.tool.finished":
            self = .toolFinished(
                bot: try bot(),
                toolUseId: try d.decode(String.self, forKey: .toolUseId),
                isError: try d.decodeIfPresent(Bool.self, forKey: .isError) ?? false
            )
        case "bot.turn.completed":
            self = .turnCompleted(bot: try bot(), messageId: try d.decodeIfPresent(String.self, forKey: .messageId))
        case "bot.settings.changed":
            self = .settingsChanged(
                bot: try bot(),
                model: try d.decode(String.self, forKey: .model),
                effort: try d.decode(String.self, forKey: .effort)
            )
        case "bot.added":
            self = .botAdded(try bot())
        case "bot.updated":
            self = .botUpdated(try c.decode(Pal.self, forKey: .data))
        case "bot.removed":
            self = .botRemoved(try bot())
        case "display.state":
            self = .display(try d.decode(Display.self, forKey: .display))
        default:
            self = .unknown
        }
    }
}

/// A tool call a bot made, as shown in the chat's work pill.
nonisolated struct ToolCall: Identifiable, Hashable, Sendable {
    let id: String
    let tool: String
    let input: JSONValue
    var finished = false
    var failed = false
}

// MARK: - Request bodies

/// `PATCH /v1/bots/{id}`: only the fields that are set change.
nonisolated struct BotEdit: Encodable, Equatable {
    var name: String?
    var role: String?
    var persona: String?
    var model: String?
    var effort: String?
    var color: String?
}

nonisolated struct ModelUpdate: Encodable {
    var model: String?
    var effort: String?
}

nonisolated struct MemoryInput: Encodable {
    var title: String
    var content: String
    var description: String
    var tags: [String]
}

// MARK: - JSON helpers

/// Arbitrary JSON, used for tool inputs and message metadata.
nonisolated enum JSONValue: Codable, Hashable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case array([JSONValue])
    case object([String: JSONValue])
    case null

    init(from decoder: any Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    func encode(to encoder: any Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .number(let n): try c.encode(n)
        case .bool(let b): try c.encode(b)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        case .null: try c.encodeNil()
        }
    }

    /// Looks a key up as written and in camelCase: the decoder converts the
    /// runtime's snake_case keys, including those inside tool inputs.
    subscript(key: String) -> JSONValue? {
        guard case .object(let o) = self else { return nil }
        if let value = o[key] { return value }
        let parts = key.split(separator: "_")
        let camel = (parts.first.map(String.init) ?? "") + parts.dropFirst().map { $0.capitalized }.joined()
        return o[camel]
    }

    var string: String? {
        if case .string(let s) = self { s } else { nil }
    }

    /// First string value found, for describing unfamiliar tool inputs.
    var firstString: String? {
        switch self {
        case .string(let s): s
        case .array(let a): a.lazy.compactMap(\.firstString).first
        case .object(let o): o.keys.sorted().lazy.compactMap { o[$0]?.firstString }.first
        default: nil
        }
    }
}

nonisolated enum PalDate {
    static func parse(_ s: String) -> Date? {
        // The runtime writes microseconds ("…:00.025992+00:00"); keep milliseconds.
        let s = s.replacingOccurrences(of: #"(\.\d{3})\d+"#, with: "$1", options: .regularExpression)
        return (try? Date.ISO8601FormatStyle(includingFractionalSeconds: true).parse(s))
            ?? (try? Date.ISO8601FormatStyle().parse(s))
    }
}

nonisolated extension JSONDecoder {
    static func pal() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { decoder in
            let s = try decoder.singleValueContainer().decode(String.self)
            if let date = PalDate.parse(s) { return date }
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath, debugDescription: "Unreadable date: \(s)"))
        }
        return decoder
    }
}
