import AppKit
import SwiftUI

/// A floating search bar over the Pal window, like Spotlight. Results grow
/// out of the bar as you type, inside the same glass.
final class SearchPanel {
    static let shared = SearchPanel()

    /// The bar's width, plus room around it for its shadow.
    private static let width: CGFloat = 600
    private static let margin: CGFloat = 40
    private static let maxResultsHeight: CGFloat = 380

    private var panel: FloatingPanel?
    private var resignObserver: NSObjectProtocol?

    var isShown: Bool { panel?.isVisible == true }

    func toggle(store: PalStore) {
        if isShown { close() } else { show(store: store) }
    }

    func show(store: PalStore) {
        close()
        let parent = NSApp.keyWindow ?? NSApp.mainWindow
        let size = NSSize(
            width: Self.width + Self.margin * 2,
            height: SearchView.barHeight + Self.maxResultsHeight + Self.margin * 2
        )
        let panel = FloatingPanel(contentRect: NSRect(origin: .zero, size: size))
        let host = NSHostingView(
            rootView: SearchView(maxResultsHeight: Self.maxResultsHeight, close: { [weak self] in self?.close() })
                .padding(Self.margin)
                .frame(width: size.width, height: size.height, alignment: .top)
                .environment(store)
        )
        // The panel keeps one size; only the glass inside grows, so the bar never moves.
        host.sizingOptions = []
        panel.contentView = host
        if let parent {
            // Centered over the window, a little below its toolbar.
            let frame = parent.frame
            panel.setFrameOrigin(NSPoint(
                x: frame.midX - size.width / 2,
                y: frame.maxY - 110 - size.height + Self.margin
            ))
        } else {
            panel.center()
        }
        resignObserver = NotificationCenter.default.addObserver(
            forName: NSWindow.didResignKeyNotification, object: panel, queue: .main
        ) { [weak self] _ in
            // Clicking anywhere else puts it away.
            MainActor.assumeIsolated { self?.close() }
        }
        self.panel = panel
        panel.makeKeyAndOrderFront(nil)
    }

    func close() {
        if let resignObserver { NotificationCenter.default.removeObserver(resignObserver) }
        resignObserver = nil
        panel?.orderOut(nil)
        panel = nil
    }
}

/// Borderless and see-through, so only the glass bar shows; it floats above
/// Pal's windows and can take typing.
private final class FloatingPanel: NSPanel {
    init(contentRect: NSRect) {
        super.init(contentRect: contentRect, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isFloatingPanel = true
        level = .floating
        backgroundColor = .clear
        isOpaque = false
        hasShadow = false
        isReleasedWhenClosed = false
        collectionBehavior = [.fullScreenAuxiliary, .moveToActiveSpace, .transient]
    }

    override var canBecomeKey: Bool { true }
}

// MARK: - Search view

struct SearchView: View {
    static let barHeight: CGFloat = 54

    @Environment(PalStore.self) private var store
    let maxResultsHeight: CGFloat
    let close: () -> Void

    @State private var query = ""
    @State private var highlighted = 0
    /// Set only by the arrow keys, so hovering never scrolls the list.
    @State private var scrollTarget: String?
    /// Whether more results are hidden below, which fades the list's bottom edge.
    @State private var moreBelow = false
    var body: some View {
        let sections = SearchResults.find(query, in: store)
        let results = sections.flatMap(\.results)
        VStack(spacing: 0) {
            bar(results)
            if !query.trimmingCharacters(in: .whitespaces).isEmpty {
                Divider().padding(.horizontal, 14)
                // No fade: the results are already in place, and the glass
                // uncovers them as it grows, so the bar opens downward.
                resultsList(sections, all: results)
                    .transition(.identity)
            }
        }
        .frame(width: 600)
        .clipShape(.rect(cornerRadius: 26))
        .glassEffect(.regular, in: .rect(cornerRadius: 26))
        .shadow(color: .black.opacity(0.18), radius: 24, y: 10)
        .animation(.smooth(duration: 0.32), value: results.map(\.id))
        .onChange(of: query) { highlighted = 0 }
    }

    private func bar(_ results: [SearchResult]) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 19, weight: .medium))
                .foregroundStyle(.secondary)
            SearchField(
                text: $query,
                placeholder: "Search bots, messages, and memory",
                onMove: { step in
                    highlighted = min(max(highlighted + step, 0), max(results.count - 1, 0))
                    if results.indices.contains(highlighted) { scrollTarget = results[highlighted].id }
                },
                onSubmit: { open(results, at: highlighted) },
                onCancel: close
            )
            if !query.isEmpty {
                Button("Clear", systemImage: "xmark.circle.fill") { query = "" }
                    .labelStyle(.iconOnly)
                    .buttonStyle(.plain)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.horizontal, 18)
        .frame(height: Self.barHeight)
    }

    @ViewBuilder
    private func resultsList(_ sections: [SearchSection], all: [SearchResult]) -> some View {
        if all.isEmpty {
            Text("No results for “\(query)”")
                .font(.callout)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 22)
        } else {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(sections) { section in
                            Text(section.title)
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 12)
                                .padding(.top, 10)
                                .padding(.bottom, 2)
                            ForEach(section.results) { result in
                                let index = all.firstIndex { $0.id == result.id } ?? 0
                                ResultRow(result: result, highlighted: index == highlighted)
                                    .id(result.id)
                                    .onTapGesture { open(all, at: index) }
                                    .accessibilityElement(children: .combine)
                                    .accessibilityAddTraits(.isButton)
                                    .accessibilityAction { open(all, at: index) }
                                    .onHover { if $0 { highlighted = index } }
                            }
                        }
                    }
                    .padding(8)
                }
                .scrollBounceBehavior(.basedOnSize)
                .onScrollGeometryChange(for: Bool.self) { geometry in
                    geometry.contentOffset.y + geometry.containerSize.height < geometry.contentSize.height - 2
                } action: { _, hidden in
                    withAnimation(.easeOut(duration: 0.2)) { moreBelow = hidden }
                }
                // Results scrolled out of view melt into the glass rather than being cut off.
                .mask {
                    VStack(spacing: 0) {
                        Rectangle()
                        LinearGradient(colors: [.black, .black.opacity(0)], startPoint: .top, endPoint: .bottom)
                            .frame(height: moreBelow ? 44 : 0)
                    }
                }
                .frame(maxHeight: maxResultsHeight)
                .fixedSize(horizontal: false, vertical: true)
                .onChange(of: scrollTarget) { _, id in
                    guard let id else { return }
                    withAnimation(.smooth(duration: 0.25)) { proxy.scrollTo(id) }
                }
            }
        }
    }

    private func open(_ results: [SearchResult], at index: Int) {
        guard results.indices.contains(index) else { return }
        results[index].open(store)
        close()
        NSApp.activate()
    }
}

private struct ResultRow: View {
    @Environment(PalStore.self) private var store
    let result: SearchResult
    let highlighted: Bool

    var body: some View {
        HStack(spacing: 10) {
            icon.frame(width: 26, height: 26)
            VStack(alignment: .leading, spacing: 1) {
                Text(result.title)
                    .font(.system(size: 13, weight: .medium))
                    .lineLimit(1)
                if let subtitle = result.subtitle {
                    Text(subtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(highlighted ? .white.opacity(0.85) : .secondary)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 8)
            if let date = result.date {
                Text(Fmt.listTime(date))
                    .font(.system(size: 11))
                    .foregroundStyle(highlighted ? .white.opacity(0.8) : .secondary)
            }
        }
        .foregroundStyle(highlighted ? .white : .primary)
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(highlighted ? Color.palAccent : .clear)
        )
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private var icon: some View {
        switch result.icon {
        case .bot(let id):
            if let pal = store.pal(id) { AvatarView(pal: pal, size: 24) } else { symbol("person.circle") }
        case .symbol(let name):
            symbol(name)
        }
    }

    private func symbol(_ name: String) -> some View {
        Image(systemName: name)
            .font(.system(size: 15))
            .foregroundStyle(highlighted ? .white : Color.palAccent)
    }
}

// MARK: - Results

struct SearchResult: Identifiable {
    enum Icon {
        case bot(String)
        case symbol(String)
    }

    let id: String
    let icon: Icon
    let title: String
    var subtitle: String?
    var date: Date?
    let open: (PalStore) -> Void
}

struct SearchSection: Identifiable {
    let title: String
    let results: [SearchResult]
    var id: String { title }
}

enum SearchResults {
    static func find(_ raw: String, in store: PalStore) -> [SearchSection] {
        let q = raw.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return [] }
        func matches(_ text: String) -> Bool { text.localizedCaseInsensitiveContains(q) }

        var places: [SearchResult] = []
        if matches("Memory") {
            places.append(SearchResult(id: "place-memory", icon: .symbol("brain"), title: "Memory", open: { $0.selection = .memory }))
        }
        if matches("Computer") {
            places.append(SearchResult(id: "place-computer", icon: .symbol("display"), title: "Computer", open: { $0.selection = .computer }))
        }

        let bots = store.sortedPals
            .filter { matches($0.name) || matches($0.role) }
            .map { pal in
                SearchResult(id: "bot-\(pal.id)", icon: .bot(pal.id), title: pal.name,
                             subtitle: pal.role.isEmpty ? nil : pal.role, open: { $0.open(pal.id) })
            }

        let messages = store.messages
            .flatMap { bot, list in list.map { (bot, $0) } }
            .filter { matches($0.1.content) }
            .sorted { $0.1.createdAt > $1.1.createdAt }
            .prefix(20)
            .map { bot, message in
                SearchResult(
                    id: "message-\(message.id)",
                    icon: .bot(bot),
                    title: message.sender == "user" ? "You to \(store.name(of: bot))" : store.name(of: bot),
                    subtitle: snippet(message.content, around: q),
                    date: message.createdAt,
                    open: { $0.reveal(message.id, in: bot) }
                )
            }

        let scoped = store.sharedMemory.map { ("shared", $0) }
            + store.botMemory.sorted { $0.key < $1.key }.flatMap { scope, entries in entries.map { (scope, $0) } }
        let memories = scoped
            .filter { matches($0.1.title) || matches($0.1.description) || matches($0.1.body) }
            .prefix(10)
            .map { scope, entry in
                SearchResult(
                    id: "memory-\(scope)-\(entry.id)",
                    icon: .symbol("brain"),
                    title: entry.title,
                    subtitle: [scope == "shared" ? "Shared" : store.name(of: scope),
                               entry.description.isEmpty ? snippet(entry.body, around: q) : entry.description]
                        .joined(separator: " · "),
                    date: entry.updatedAt,
                    open: { $0.reveal(memory: entry.id, scope: scope) }
                )
            }

        return [
            SearchSection(title: "Go to", results: places),
            SearchSection(title: "Bots", results: bots),
            SearchSection(title: "Messages", results: Array(messages)),
            SearchSection(title: "Memory", results: Array(memories)),
        ].filter { !$0.results.isEmpty }
    }

    /// One line of text around the first match, so the match is visible.
    private static func snippet(_ text: String, around query: String) -> String {
        let flat = text.replacingOccurrences(of: "\n", with: " ")
        guard let range = flat.range(of: query, options: .caseInsensitive) else { return flat }
        let start = flat.index(range.lowerBound, offsetBy: -40, limitedBy: flat.startIndex) ?? flat.startIndex
        return (start > flat.startIndex ? "…" : "") + flat[start...]
    }
}

// MARK: - Field

/// The bar's text field. It takes typing from the moment it's added to the
/// panel, before the panel is first drawn, so you can type right away and the
/// text never shifts when editing starts (SwiftUI's field moves a pixel then).
private struct SearchField: NSViewRepresentable {
    @Binding var text: String
    let placeholder: String
    let onMove: (Int) -> Void
    let onSubmit: () -> Void
    let onCancel: () -> Void

    func makeNSView(context: Context) -> FocusingTextField {
        let field = FocusingTextField()
        field.delegate = context.coordinator
        field.isBordered = false
        field.isBezeled = false
        field.drawsBackground = false
        field.focusRingType = .none
        field.font = .systemFont(ofSize: 20)
        field.usesSingleLineMode = true
        field.lineBreakMode = .byTruncatingTail
        field.cell?.isScrollable = true
        field.placeholderAttributedString = NSAttributedString(string: placeholder, attributes: [
            .font: NSFont.systemFont(ofSize: 20),
            .foregroundColor: NSColor.placeholderTextColor,
        ])
        field.setContentHuggingPriority(.defaultLow, for: .horizontal)
        return field
    }

    func updateNSView(_ field: FocusingTextField, context: Context) {
        context.coordinator.parent = self
        if field.stringValue != text {
            field.stringValue = text
            field.moveCaretToEnd()
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(parent: self) }

    final class Coordinator: NSObject, NSTextFieldDelegate {
        var parent: SearchField

        init(parent: SearchField) { self.parent = parent }

        func controlTextDidChange(_ notification: Notification) {
            guard let field = notification.object as? NSTextField else { return }
            parent.text = field.stringValue
        }

        func control(_ control: NSControl, textView: NSTextView, doCommandBy selector: Selector) -> Bool {
            switch selector {
            case #selector(NSResponder.moveUp(_:)): parent.onMove(-1)
            case #selector(NSResponder.moveDown(_:)): parent.onMove(1)
            case #selector(NSResponder.insertNewline(_:)): parent.onSubmit()
            case #selector(NSResponder.cancelOperation(_:)): parent.onCancel()
            default: return false
            }
            return true
        }
    }
}

final class FocusingTextField: NSTextField {
    private var hasFocused = false

    /// Takes typing the first time the field lands in a window, and only then:
    /// SwiftUI moves the field between containers as the panel redraws, and
    /// taking focus again would select everything typed so far.
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        guard !hasFocused, let window else { return }
        hasFocused = true
        window.makeFirstResponder(self)
        moveCaretToEnd()
    }

    /// Becoming first responder selects all the text; put the cursor after it instead.
    func moveCaretToEnd() {
        guard let editor = currentEditor() else { return }
        editor.selectedRange = NSRange(location: (stringValue as NSString).length, length: 0)
    }
}
