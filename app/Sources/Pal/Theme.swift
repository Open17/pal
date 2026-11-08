import AppKit
import SwiftUI

// MARK: - Colors

nonisolated extension NSColor {
    convenience init(hex: UInt32, alpha: CGFloat = 1) {
        self.init(
            srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: alpha
        )
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(nsColor: NSColor(hex: hex))
    }

    /// A color that follows the system's light/dark appearance.
    static func adaptive(_ light: UInt32, _ dark: UInt32) -> Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? NSColor(hex: dark) : NSColor(hex: light)
        })
    }

    /// The app's theme color: buttons, badges, the selected sidebar row.
    static let palAccent = Color(.sRGB, red: 0.000, green: 0.533, blue: 1.000)
    static let chatBackground = Color(nsColor: .textBackgroundColor)
    static let card = Color(nsColor: .controlBackgroundColor)
    static let incomingBubble = adaptive(0xEDEEF3, 0x2A2B31)
    static let hairline = Color(nsColor: .separatorColor)

    static let statusGreen = Color(nsColor: .systemGreen)
    static let statusOrange = Color(nsColor: .systemOrange)
    static let statusRed = Color(nsColor: .systemRed)

    /// Your sent messages.
    static let outgoingBubble = Color(.sRGB, red: 0.039, green: 0.553, blue: 0.996)
}

// MARK: - Avatars

/// A round avatar. Bots get the bot mark in their own color; anything else
/// shows a symbol, an emoji or initials.
struct AvatarView: View {
    var label: String
    var name: String
    var seed: String
    var color: String?
    var size: CGFloat = 40
    var status: PalStatus?
    var symbol: String?
    var isBot = false

    init(pal: Pal, size: CGFloat = 40, showStatus: Bool = false) {
        label = ""
        name = pal.name
        seed = pal.id
        color = pal.color
        self.size = size
        status = showStatus ? pal.status : nil
        isBot = true
    }

    /// A bot that isn't loaded (yet), drawn from a color alone, e.g. in the New Bot sheet.
    init(botColor: String?, seed: String, size: CGFloat = 40) {
        label = ""
        name = ""
        self.seed = seed
        color = botColor
        self.size = size
        isBot = true
    }

    init(label: String = "", name: String, seed: String, size: CGFloat = 40, symbol: String? = nil) {
        self.label = label
        self.name = name
        self.seed = seed
        self.size = size
        self.symbol = symbol
    }

    var body: some View {
        let palette = BotTint.of(color: color, seed: seed)
        Circle()
            .fill(palette.fill)
            .overlay { if palette.needsOutline { Circle().strokeBorder(Color.primary.opacity(0.15), lineWidth: 1) } }
            .overlay { content(palette) }
            .frame(width: size, height: size)
            .overlay(alignment: .bottomTrailing) {
                if let status {
                    StatusDot(status: status, size: max(11, size * 0.3))
                        .offset(x: size * 0.02, y: size * 0.02)
                }
            }
    }

    @ViewBuilder
    private func content(_ palette: BotTint) -> some View {
        if isBot {
            BlinkingBotMark(ink: palette.ink)
                .frame(width: size * 0.62, height: size * 0.62)
                .accessibilityLabel(name)
        } else if let symbol {
            Image(systemName: symbol)
                .font(.system(size: size * 0.42, weight: .semibold))
                .foregroundStyle(palette.ink)
        } else if label.isEmojiOnly {
            Text(label).font(.system(size: size * 0.5))
        } else {
            Text(initials)
                .font(.system(size: size * 0.38, weight: .semibold, design: .rounded))
                .foregroundStyle(palette.ink)
        }
    }

    private var initials: String {
        if !label.isEmpty { return String(label.prefix(2)) }
        let letters = name.split(separator: " ").prefix(2).compactMap(\.first)
        return letters.isEmpty ? "?" : String(letters).uppercased()
    }
}

/// Presence dot drawn over an avatar, with a ring in the window background color.
struct StatusDot: View {
    let status: PalStatus
    var size: CGFloat = 12

    var body: some View {
        Circle()
            .fill(status.color)
            .padding(size * 0.17)
            .background(Circle().fill(Color.chatBackground))
            .frame(width: size, height: size)
    }
}

extension PalStatus {
    var color: Color {
        switch self {
        case .offline: Color(nsColor: .systemGray)
        case .idle: .statusGreen
        case .busy: .palAccent
        case .waiting, .signedOut: .statusOrange
        case .error: .statusRed
        }
    }
}

extension PalStore {
    func statusLabel(_ pal: Pal) -> String {
        switch pal.status {
        case .offline: "Offline"
        case .idle: "Online"
        case .signedOut: "Not signed in"
        case .busy: "Working…"
        case .waiting(let mate): "Waiting on \(name(of: mate))"
        case .error: "Hit a snag"
        }
    }
}

enum DisplayState {
    static func label(_ state: String) -> String {
        switch state {
        case "running": "Awake"
        case "sleeping": "Asleep (windows kept)"
        case "starting": "Starting…"
        case "failed": "Failed"
        default: "Off"
        }
    }

    static func color(_ state: String) -> Color {
        switch state {
        case "running": .statusGreen
        case "sleeping": .statusOrange
        case "starting": .palAccent
        case "failed": .statusRed
        default: Color(nsColor: .systemGray)
        }
    }
}

/// The models a bot can run, and how to name them.
enum Models {
    struct Option {
        let id: String
        let name: String
    }

    static let all: [Option] = [
        Option(id: "claude-sonnet-5-5", name: "Sonnet 5.5"),
        Option(id: "claude-opus-5-5", name: "Opus 5.5"),
        Option(id: "claude-haiku-5-5", name: "Haiku 5.5"),
        Option(id: "claude-fable-5-1", name: "Fable 5.1"),
    ]

    static func name(_ id: String) -> String {
        all.first { $0.id == id }?.name ?? id
    }

    static func shortName(_ id: String) -> String {
        name(id)
    }

    static func effortName(_ level: String) -> String {
        level == "xhigh" ? "Extra high" : level.prefix(1).uppercased() + level.dropFirst()
    }
}

// MARK: - Text helpers

extension String {
    /// A short run of emoji with no other text, shown large without a bubble.
    var isEmojiOnly: Bool {
        let t = trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty, t.count <= 4 else { return false }
        return t.allSatisfy { c in
            if c.isWhitespace { return true }
            guard let first = c.unicodeScalars.first else { return false }
            return first.properties.isEmojiPresentation || (c.unicodeScalars.count > 1 && first.properties.isEmoji)
        }
    }

    /// One line of plain text for list previews.
    var previewLine: String {
        // Drop code-fence markers along with their language tag, then inline markup.
        var s = replacingOccurrences(of: "```[A-Za-z0-9_+-]*", with: " ", options: .regularExpression)
        for token in ["**", "__", "`", "#"] { s = s.replacingOccurrences(of: token, with: "") }
        return s.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }
}

enum Fmt {
    static func time(_ date: Date) -> String {
        date.formatted(date: .omitted, time: .shortened)
    }

    /// Chat-list style: time today, "Yesterday", weekday this week, else a short date.
    static func listTime(_ date: Date) -> String {
        let cal = Calendar.current
        if cal.isDateInToday(date) { return time(date) }
        if cal.isDateInYesterday(date) { return "Yesterday" }
        if let days = cal.dateComponents([.day], from: date, to: .now).day, days < 7 {
            return date.formatted(.dateTime.weekday(.wide))
        }
        return date.formatted(.dateTime.month(.abbreviated).day())
    }

    static func day(_ date: Date) -> String {
        let cal = Calendar.current
        if cal.isDateInToday(date) { return "Today" }
        if cal.isDateInYesterday(date) { return "Yesterday" }
        return date.formatted(.dateTime.weekday(.wide).month(.wide).day())
    }

    static func relative(_ date: Date) -> String {
        let cal = Calendar.current
        if cal.isDateInToday(date) { return "Today at \(time(date))" }
        if cal.isDateInTomorrow(date) { return "Tomorrow at \(time(date))" }
        return date.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day().hour().minute())
    }
}

// MARK: - Tools

struct ToolStep {
    let symbol: String
    let text: String
    /// The command, file, or address, when there is one.
    let detail: String?
}

enum Tools {
    static func shortName(_ tool: String) -> String {
        tool.hasPrefix("mcp__") ? (tool.components(separatedBy: "__").last ?? tool) : tool
    }

    /// Tools whose result shows elsewhere in the chat, not as a work step.
    static func shownElsewhere(_ tool: String) -> Bool {
        ["message_bot", "react"].contains(shortName(tool))
    }

    static func describe(_ tool: String, _ input: JSONValue) -> ToolStep {
        let file = input["file_path"]?.string ?? input["path"]?.string
        let fileName = file.map { URL(fileURLWithPath: $0).lastPathComponent }
        switch shortName(tool) {
        case "Bash":
            let command = input["command"]?.string
            return ToolStep(symbol: "terminal", text: input["description"]?.string ?? "Ran a command", detail: command)
        case "Read":
            return ToolStep(symbol: "doc.text", text: "Read \(fileName ?? "a file")", detail: file)
        case "Write":
            return ToolStep(symbol: "doc.badge.plus", text: "Wrote \(fileName ?? "a file")", detail: file)
        case "Edit", "MultiEdit", "NotebookEdit":
            return ToolStep(symbol: "pencil.line", text: "Edited \(fileName ?? "a file")", detail: file)
        case "Glob", "Grep":
            let pattern = input["pattern"]?.string
            return ToolStep(symbol: "magnifyingglass", text: pattern.map { "Searched for “\($0)”" } ?? "Searched files", detail: nil)
        case "WebFetch":
            let url = input["url"]?.string
            let host = url.flatMap { URL(string: $0)?.host() }
            return ToolStep(symbol: "globe", text: "Opened \(host ?? "a web page")", detail: url)
        case "WebSearch":
            let query = input["query"]?.string
            return ToolStep(symbol: "globe", text: query.map { "Searched the web for “\($0)”" } ?? "Searched the web", detail: nil)
        case "Task", "Agent":
            return ToolStep(symbol: "sparkles", text: input["description"]?.string.map { "Started a helper: \($0)" } ?? "Started a helper", detail: nil)
        case "TodoWrite":
            return ToolStep(symbol: "checklist", text: "Updated the plan", detail: nil)
        case "message_bot":
            let to = input["to"]?.string.map { $0.prefix(1).uppercased() + $0.dropFirst() }
            let asked = input["wait_for_reply"] == .bool(true)
            return ToolStep(symbol: "paperplane", text: "\(asked ? "Asked" : "Messaged") \(to ?? "a teammate")", detail: input["message"]?.string)
        case "react":
            return ToolStep(symbol: "face.smiling", text: "Reacted \(input["emoji"]?.string ?? "")", detail: nil)
        case "list_bots":
            return ToolStep(symbol: "person.3", text: "Checked who's on the team", detail: nil)
        case "remember":
            return ToolStep(symbol: "brain", text: "Remembered “\(input["title"]?.string ?? "something")”", detail: nil)
        case "recall":
            return ToolStep(symbol: "brain", text: "Searched memory for “\(input["query"]?.string ?? "")”", detail: nil)
        case "read_memory":
            return ToolStep(symbol: "brain", text: "Read a memory", detail: input["id"]?.string)
        case "forget":
            return ToolStep(symbol: "brain", text: "Forgot a memory", detail: input["id"]?.string)
        case "use_display":
            return ToolStep(symbol: "display", text: "Turned on their display", detail: nil)
        case "display_status":
            return ToolStep(symbol: "display", text: "Checked their display", detail: nil)
        default:
            let name = shortName(tool).replacingOccurrences(of: "_", with: " ")
            return ToolStep(symbol: "wrench.and.screwdriver", text: "Used \(name)", detail: input.firstString)
        }
    }
}
