import AppKit
import SwiftUI

// MARK: - Timeline

struct MessageRow: Hashable {
    enum Sender: Hashable {
        case me
        case pal
        case teammate(id: String)
    }

    let message: Message
    let sender: Sender
    var isFirst = true
    var isLast = true
}

enum TimelineItem: Identifiable, Hashable {
    case day(Date)
    case message(MessageRow)
    /// The tool calls a bot made before a reply.
    case work(id: String, calls: [ToolCall])
    /// Messages the bot traded with teammates in between.
    case team(id: String, messages: [Message])
    case note(Message)

    var id: String {
        switch self {
        case .day(let d): "day-\(d.timeIntervalSince1970)"
        case .message(let m): m.message.id
        case .work(let id, _): id
        case .team(let id, _): id
        case .note(let m): m.id
        }
    }
}

enum Timeline {
    /// Messages from the same sender within this window share one header.
    static let groupWindow: TimeInterval = 5 * 60

    static func build(_ messages: [Message], palId: String, work: [String: [ToolCall]], team: [Message] = []) -> [TimelineItem] {
        var items: [TimelineItem] = []
        var day: Date?
        func startDay(_ date: Date) {
            if day.map({ !Calendar.current.isDate(date, inSameDayAs: $0) }) ?? true {
                items.append(.day(Calendar.current.startOfDay(for: date)))
                day = date
            }
        }
        // Teammate messages sent before each chat message, as one pill.
        var pending = team[...]
        func flushTeam(before date: Date?) {
            let run = pending.prefix { date == nil || $0.createdAt <= date! }
            guard let first = run.first else { return }
            pending = pending.dropFirst(run.count)
            startDay(first.createdAt)
            items.append(.team(id: "team-\(first.id)", messages: Array(run)))
        }
        for message in messages {
            flushTeam(before: message.createdAt)
            startDay(message.createdAt)
            // Messages to teammates show in their own pill (see `TeamExchangeView`).
            if let calls = work[message.id]?.filter({ Tools.shortName($0.tool) != "message_bot" }), !calls.isEmpty {
                items.append(.work(id: "work-\(message.id)", calls: calls))
            }
            if message.isError {
                items.append(.note(message))
                continue
            }
            let sender: MessageRow.Sender = message.sender == "user" ? .me
                : message.sender == palId ? .pal : .teammate(id: message.sender)
            items.append(.message(MessageRow(message: message, sender: sender)))
        }
        flushTeam(before: nil)

        // Group consecutive messages from the same sender. Work in between
        // doesn't break a bot's group, so its header shows once.
        func neighbor(of i: Int, step: Int) -> MessageRow? {
            var j = i + step
            while items.indices.contains(j) {
                switch items[j] {
                case .message(let row): return row
                case .work, .team: j += step
                default: return nil
                }
            }
            return nil
        }
        for i in items.indices {
            guard case .message(var row) = items[i] else { continue }
            if let prev = neighbor(of: i, step: -1) {
                row.isFirst = !(prev.sender == row.sender && row.message.createdAt.timeIntervalSince(prev.message.createdAt) < groupWindow)
            }
            if let next = neighbor(of: i, step: 1) {
                row.isLast = !(next.sender == row.sender && next.message.createdAt.timeIntervalSince(row.message.createdAt) < groupWindow)
            }
            items[i] = .message(row)
        }
        return items
    }
}

// MARK: - Message row

struct MessageRowView: View {
    /// Space reserved for the avatar column, so bubbles and work steps line up.
    static let gutter: CGFloat = 38

    @Environment(PalStore.self) private var store
    let row: MessageRow
    let pal: Pal

    var body: some View {
        Group {
            if row.sender == .me {
                HStack(spacing: 0) {
                    Spacer(minLength: 100)
                    VStack(alignment: .trailing, spacing: 3) {
                        if row.isFirst {
                            Text(Fmt.time(row.message.createdAt))
                                .font(.system(size: 10.5))
                                .foregroundStyle(.tertiary)
                                .padding(.trailing, 4)
                        }
                        content(outgoing: true)
                    }
                }
            } else {
                HStack(alignment: .top, spacing: 0) {
                    Group {
                        if row.isFirst { avatar } else { Color.clear.frame(height: 1) }
                    }
                    .frame(width: Self.gutter, alignment: .leading)
                    VStack(alignment: .leading, spacing: 3) {
                        if row.isFirst { header }
                        content(outgoing: false)
                    }
                    Spacer(minLength: 100)
                }
            }
        }
        .padding(.top, row.isFirst ? 10 : 0)
    }

    @ViewBuilder
    private var avatar: some View {
        switch row.sender {
        case .pal:
            AvatarView(pal: pal, size: 28)
        case .teammate(let id):
            if let mate = store.pal(id) {
                AvatarView(pal: mate, size: 28)
            } else {
                AvatarView(name: id, seed: id, size: 28)
            }
        case .me:
            EmptyView()
        }
    }

    private var header: some View {
        HStack(spacing: 6) {
            switch row.sender {
            case .pal:
                Text(pal.name).font(.system(size: 12, weight: .semibold))
            case .teammate(let id):
                Text(store.name(of: id)).font(.system(size: 12, weight: .semibold))
                Tag(text: "Teammate")
            case .me:
                EmptyView()
            }
            Text(Fmt.time(row.message.createdAt))
                .font(.system(size: 10.5))
                .foregroundStyle(.tertiary)
        }
        .padding(.leading, 4)
    }

    @ViewBuilder
    private func content(outgoing: Bool) -> some View {
        let text = row.message.content
        if text.isEmojiOnly {
            Text(text.trimmingCharacters(in: .whitespaces))
                .font(.system(size: 40))
        } else {
            RichText(text: text, inverted: outgoing)
                .bubble(outgoing: outgoing, first: row.isFirst, last: row.isLast)
                .contextMenu {
                    Button("Copy") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(text, forType: .string)
                    }
                }
        }
    }
}

struct Tag: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.system(size: 10, weight: .medium))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 5)
            .padding(.vertical, 1)
            .background(Capsule().fill(Color.primary.opacity(0.07)))
    }
}

extension View {
    /// Wraps content in a chat bubble. Outgoing bubbles are tinted and right-aligned.
    func bubble(outgoing: Bool, first: Bool, last: Bool) -> some View {
        let shape = BubbleShape(outgoing: outgoing, first: first, last: last)
        return self
            .foregroundStyle(outgoing ? Color.white : Color.primary)
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background {
                if outgoing { shape.fill(Color.outgoingBubble) } else { shape.fill(Color.incomingBubble) }
            }
            .frame(maxWidth: 560, alignment: outgoing ? .trailing : .leading)
    }
}

/// Rounded bubble whose corners tighten where it joins its neighbors in a group.
nonisolated struct BubbleShape: Shape {
    let outgoing: Bool
    let first: Bool
    let last: Bool

    func path(in rect: CGRect) -> Path {
        let big: CGFloat = 16
        let small: CGFloat = 5
        let joinTop = first ? big : small
        let joinBottom = last ? big : small
        let radii = outgoing
            ? RectangleCornerRadii(topLeading: big, bottomLeading: big, bottomTrailing: joinBottom, topTrailing: joinTop)
            : RectangleCornerRadii(topLeading: joinTop, bottomLeading: joinBottom, bottomTrailing: big, topTrailing: big)
        return UnevenRoundedRectangle(cornerRadii: radii, style: .continuous).path(in: rect)
    }
}

// MARK: - Rich text

/// Light Markdown: inline styles, headings, bullets, and fenced code blocks.
struct RichText: View {
    let text: String
    var inverted = false

    private enum Block: Hashable {
        case prose(String)
        case code(String)
    }

    var body: some View {
        let blocks = Self.blocks(text)
        if blocks.count == 1, case .prose(let s) = blocks[0] {
            prose(s)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                    switch block {
                    case .prose(let s): prose(s)
                    case .code(let s): code(s)
                    }
                }
            }
        }
    }

    private func prose(_ s: String) -> some View {
        Text(Self.inline(s, inverted: inverted))
            .tint(inverted ? .white : .primary)
            .font(.system(size: 13))
            .lineSpacing(1.5)
            .textSelection(.enabled)
            .fixedSize(horizontal: false, vertical: true)
            // Links open only on ⌘-click, so a plain click can select text.
            .environment(\.openURL, OpenURLAction { url in
                NSEvent.modifierFlags.contains(.command) ? .systemAction(url) : .handled
            })
    }

    private func code(_ s: String) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            Text(s)
                .font(.system(size: 11.5, design: .monospaced))
                .textSelection(.enabled)
                .padding(9)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(inverted ? Color.white.opacity(0.14) : Color.primary.opacity(0.06)))
    }

    private static func blocks(_ text: String) -> [Block] {
        var out: [Block] = []
        for (i, part) in text.components(separatedBy: "```").enumerated() {
            if i % 2 == 1 {
                var lines = part.split(separator: "\n", omittingEmptySubsequences: false)
                if lines.count > 1, let first = lines.first, !first.contains(" ") { lines.removeFirst() } // language tag
                let code = lines.joined(separator: "\n").trimmingCharacters(in: .newlines)
                if !code.isEmpty { out.append(.code(code)) }
            } else {
                let s = part.trimmingCharacters(in: .whitespacesAndNewlines)
                if !s.isEmpty { out.append(.prose(s)) }
            }
        }
        return out.isEmpty ? [.prose(text)] : out
    }

    private static func inline(_ s: String, inverted: Bool) -> AttributedString {
        let lines = s.split(separator: "\n", omittingEmptySubsequences: false).map { line -> String in
            let trimmed = line.drop { $0 == " " }
            if let hashes = trimmed.firstIndex(where: { $0 != "#" }), hashes > trimmed.startIndex,
               trimmed[hashes] == " ", trimmed.distance(from: trimmed.startIndex, to: hashes) <= 6 {
                return "**\(trimmed[trimmed.index(after: hashes)...])**"
            }
            if trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ") {
                let indent = String(repeating: "  ", count: (line.count - trimmed.count) / 2)
                return "\(indent)•  \(trimmed.dropFirst(2))"
            }
            return String(line)
        }
        let md = lines.joined(separator: "\n")
        var out = (try? AttributedString(markdown: md, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(s)
        linkBareAddresses(&out)
        // Links read as plain text, just underlined, rather than in the accent color.
        for run in out.runs where run.link != nil {
            out[run.range].foregroundColor = inverted ? .white : .primary
            out[run.range].underlineStyle = .single
        }
        return out
    }

    private static let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)

    /// Turns plain web addresses and emails into links (emails become mailto:).
    private static func linkBareAddresses(_ text: inout AttributedString) {
        guard let detector else { return }
        let plain = String(text.characters)
        for match in detector.matches(in: plain, range: NSRange(plain.startIndex..., in: plain)) {
            guard let url = match.url, let range = Range(match.range, in: plain) else { continue }
            let start = text.characters.index(text.startIndex, offsetBy: plain.distance(from: plain.startIndex, to: range.lowerBound))
            let end = text.characters.index(start, offsetBy: plain.distance(from: range.lowerBound, to: range.upperBound))
            if text[start..<end].runs.contains(where: { $0.link != nil }) { continue }
            text[start..<end].link = url
        }
    }
}

// MARK: - Work steps

/// A compact pill summarizing tool use, expandable into each step.
struct WorkGroupView: View {
    let calls: [ToolCall]
    let active: Bool
    @State private var expanded = false

    var body: some View {
        let failures = calls.filter(\.failed).count
        let steps = calls.map { Tools.describe($0.tool, $0.input) }
        if !calls.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Button {
                    withAnimation(.snappy(duration: 0.25)) { expanded.toggle() }
                } label: {
                    HStack(spacing: 7) {
                        if active {
                            ProgressView().controlSize(.mini)
                            Text(steps.last?.text ?? "Working").lineLimit(1)
                        } else {
                            Image(systemName: "checkmark.circle.fill").foregroundStyle(.secondary)
                            Text(calls.count == 1 ? steps[0].text : "Worked through \(calls.count) steps").lineLimit(1)
                        }
                        if failures > 0 {
                            Text("· \(failures) didn't work").foregroundStyle(Color.statusRed)
                        }
                        Image(systemName: "chevron.right")
                            .font(.system(size: 9, weight: .bold))
                            .rotationEffect(.degrees(expanded ? 90 : 0))
                            .foregroundStyle(.tertiary)
                    }
                    .font(.system(size: 11.5, weight: .medium))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(Capsule().strokeBorder(Color.hairline, lineWidth: 1))
                    .contentShape(Capsule())
                }
                .buttonStyle(.plain)

                if expanded {
                    VStack(alignment: .leading, spacing: 7) {
                        ForEach(Array(zip(calls, steps)), id: \.0.id) { call, step in
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Image(systemName: call.failed ? "xmark.circle.fill" : step.symbol)
                                    .foregroundStyle(call.failed ? Color.statusRed : .secondary)
                                    .frame(width: 16)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(step.text).font(.system(size: 12))
                                    if let detail = step.detail {
                                        Text(detail)
                                            .font(.system(size: 11, design: .monospaced))
                                            .foregroundStyle(.secondary)
                                            .lineLimit(3)
                                            .textSelection(.enabled)
                                    }
                                }
                            }
                        }
                    }
                    .padding(12)
                    .frame(maxWidth: 560, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.primary.opacity(0.035)))
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }
            }
        }
    }
}

// MARK: - Teammates

/// A pill like the work steps' for messages a bot traded with teammates:
/// "Pal asked Scout". Expanded, each message opens the whole conversation,
/// read-only.
struct TeamExchangeView: View {
    @Environment(PalStore.self) private var store
    let messages: [Message]
    let palId: String
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button {
                withAnimation(.snappy(duration: 0.25)) { expanded.toggle() }
            } label: {
                HStack(spacing: 7) {
                    Image(systemName: "bubble.left.and.bubble.right.fill").foregroundStyle(.secondary)
                    Text(summary).lineLimit(1)
                    Image(systemName: "chevron.right")
                        .font(.system(size: 9, weight: .bold))
                        .rotationEffect(.degrees(expanded ? 90 : 0))
                        .foregroundStyle(.tertiary)
                }
                .font(.system(size: 11.5, weight: .medium))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(Capsule().strokeBorder(Color.hairline, lineWidth: 1))
                .contentShape(Capsule())
            }
            .buttonStyle(.plain)

            if expanded {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(messages) { message in
                        Button {
                            store.sheet = .thread(id: message.conversationId, focus: message.id)
                        } label: {
                            TeamMessageLink(message: message)
                        }
                        .buttonStyle(.plain)
                        .help("Open the conversation between \(store.name(of: message.sender)) and \(store.name(of: message.recipient))")
                    }
                }
                .padding(6)
                .frame(maxWidth: 560, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.primary.opacity(0.035)))
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }

    private var summary: String {
        let me = store.name(of: palId)
        var mates: [String] = []
        for message in messages {
            for id in [message.sender, message.recipient] where id != palId && !mates.contains(id) {
                mates.append(id)
            }
        }
        guard mates.count == 1, let first = messages.first else {
            return "\(me) talked with \(ListFormatter.localizedString(byJoining: mates.map(store.name(of:))))"
        }
        let verb = first.kind == "request" ? "asked" : "messaged"
        let line = "\(store.name(of: first.sender)) \(verb) \(store.name(of: first.recipient))"
        return messages.count > 1 ? "\(line) · \(messages.count) messages" : line
    }
}

/// One teammate message in the expanded pill: who to whom, and how it starts.
private struct TeamMessageLink: View {
    @Environment(PalStore.self) private var store
    let message: Message
    @State private var hovering = false

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Group {
                if let pal = store.pal(message.sender) {
                    AvatarView(pal: pal, size: 18)
                } else {
                    AvatarView(name: store.name(of: message.sender), seed: message.sender, size: 18)
                }
            }
            .padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 5) {
                    Text(store.name(of: message.sender)).fontWeight(.semibold)
                    Image(systemName: "arrow.right").font(.system(size: 8)).foregroundStyle(.tertiary)
                    Text(store.name(of: message.recipient)).foregroundStyle(.secondary)
                    Text(Fmt.time(message.createdAt)).font(.system(size: 10.5)).foregroundStyle(.tertiary)
                }
                .font(.system(size: 12))
                Text(message.content.previewLine)
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
            }
            Spacer(minLength: 8)
            Image(systemName: "arrow.up.right.square")
                .font(.system(size: 11))
                .foregroundStyle(.tertiary)
                .opacity(hovering ? 1 : 0)
                .padding(.top, 2)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Color.primary.opacity(hovering ? 0.05 : 0)))
        .contentShape(Rectangle())
        .onHover { hovering = $0 }
    }
}
