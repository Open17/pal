import AppKit
import SwiftUI

struct ConversationView: View {
    @Environment(PalStore.self) private var store
    let pal: Pal
    @AppStorage("showInspector") private var showInspector = false
    /// Whether this bot's computer is open beside the chat; each bot remembers its own.
    private var showDisplay: Bool { store.displayOpen.contains(pal.id) }
    private var displayToggle: Binding<Bool> {
        Binding(get: { showDisplay }, set: { store.setDisplayOpen($0, for: pal.id) })
    }
    @State private var confirmReset = false
    @State private var confirmRemove = false

    var body: some View {
        Group {
            if showDisplay {
                // Sized from the available width so it always fits the window.
                GeometryReader { geometry in
                    HStack(spacing: 0) {
                        chat.frame(width: max(280, geometry.size.width * 0.45))
                        Divider()
                        DisplayView(owner: pal.id)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                            .background(Color.chatBackground)
                    }
                }
            } else {
                chat
            }
        }
        // Like Messages: a bare avatar up in the toolbar, and the name in a
        // pill just under it, hanging over the top of the conversation. With
        // the computer open beside the chat, the pill sits over the chat alone
        // and carries the avatar itself.
        .overlay(alignment: .top) {
            if !showDisplay { namePill(withAvatar: false) }
        }
        // The name is shown in the pill; the title still names the window.
        .navigationTitle(pal.name)
        .toolbar(removing: .title)
        .toolbar {
            if !showDisplay {
                ToolbarItem(placement: .principal) {
                    Button { showInspector.toggle() } label: {
                        AvatarView(pal: pal, size: 36, showStatus: true)
                            .contentShape(Circle())
                    }
                    .buttonStyle(.plain)
                    .help(detailsHelp)
                }
                .sharedBackgroundVisibility(.hidden)
            }
            if pal.status.isWorking {
                ToolbarItem(placement: .primaryAction) {
                    Button("Stop", systemImage: "stop.fill") { store.interrupt(pal.id) }
                        .help("Stop what \(pal.name) is doing (⌘.)")
                }
            }
            ToolbarItem(placement: .primaryAction) {
                ControlGroup {
                    Toggle(isOn: displayToggle) {
                        Label("Computer", systemImage: "display")
                    }
                    .help(showDisplay ? "Hide \(pal.name)’s computer" : "Watch \(pal.name)’s computer")
                    ModelMenu(pal: pal)
                    Menu {
                        // ⌘I lives in the menu bar's Bot menu, so it works without opening this.
                        Button(showInspector ? "Hide Details" : "Show Details") { showInspector.toggle() }
                        Button("Bot Settings…") { store.sheet = .botSettings(pal) }
                        Divider()
                        Button("New Conversation…") { confirmReset = true }
                        Button("Remove \(pal.name)…", role: .destructive) { confirmRemove = true }
                            .disabled(store.pals.count <= 1)
                    } label: {
                        Label("More", systemImage: "ellipsis")
                    }
                    .menuIndicator(.hidden)
                    .help("More")
                }
                .tint(.primary)
            }
        }
        .inspector(isPresented: $showInspector) {
            PalInspector(pal: pal)
                .inspectorColumnWidth(min: 260, ideal: 290, max: 360)
        }
        .confirmationDialog("Remove \(pal.name) from the team?", isPresented: $confirmRemove) {
            Button("Remove \(pal.name)", role: .destructive) { store.removeBot(pal.id) }
        } message: {
            Text("\(pal.name) stops and their display closes. Their memories and your conversation history are kept.")
        }
        .confirmationDialog("Start a new conversation with \(pal.name)?", isPresented: $confirmReset) {
            Button("New Conversation") { store.resetSession(pal.id) }
        } message: {
            Text("\(pal.name) forgets this conversation but keeps their memory. The history stays here.")
        }
    }

    private func namePill(withAvatar: Bool) -> some View {
        NamePill(name: pal.name, pal: withAvatar ? pal : nil) { showInspector.toggle() }
            .help(detailsHelp)
            // Follows the toolbar down when the menu bar shows in full screen.
            .offset(y: -6 + ToolbarDrop.shared.amount)
    }

    private var chat: some View {
        MessageList(pal: pal)
            .overlay(alignment: .top) { topFade }
            .overlay(alignment: .top) {
                if showDisplay { namePill(withAvatar: true) }
            }
            .safeAreaInset(edge: .top, spacing: 0) { SignInBanner() }
            .safeAreaInset(edge: .bottom, spacing: 0) { bottomBar }
            .background(Color.chatBackground)
    }

    private var detailsHelp: String {
        showInspector ? "Hide \(pal.name)’s details (⌘I)" : "Show \(pal.name)’s details (⌘I) · \(subtitle)"
    }

    private var subtitle: String {
        var parts: [String] = []
        if !pal.role.isEmpty { parts.append(pal.role) }
        parts.append(store.statusLabel(pal))
        if pal.queued > 0 { parts.append("\(pal.queued) queued") }
        return parts.joined(separator: " · ")
    }

    /// A deeper fade than the toolbar's own, so messages melt away under it.
    private var topFade: some View {
        LinearGradient(
            stops: [
                .init(color: Color.chatBackground.opacity(0.95), location: 0),
                .init(color: Color.chatBackground.opacity(0.7), location: 0.45),
                .init(color: Color.chatBackground.opacity(0), location: 1),
            ],
            startPoint: .top,
            endPoint: .bottom
        )
        .frame(height: 56)
        .ignoresSafeArea(edges: .top)
        .allowsHitTesting(false)
    }

    private var bottomBar: some View {
        Composer(pal: pal)
            .frame(maxWidth: 820)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 20)
            .padding(.top, 14)
            .padding(.bottom, 14)
            .background {
                // Messages fade out under the composer instead of colliding with it.
                LinearGradient(
                    stops: [.init(color: Color.chatBackground.opacity(0), location: 0), .init(color: Color.chatBackground, location: 0.4)],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .allowsHitTesting(false)
            }
    }
}

/// The bot's name with a chevron, in a glass pill under its avatar.
private struct NamePill: View {
    let name: String
    /// Shown inside the pill when there's no avatar in the toolbar above it.
    var pal: Pal?
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 3) {
                if let pal {
                    AvatarView(pal: pal, size: 18, showStatus: true)
                        .padding(.trailing, 3)
                        .padding(.leading, -5)
                }
                Text(name)
                    .font(.system(size: 12.5, weight: .semibold))
                    .lineLimit(1)
                Image(systemName: "chevron.right")
                    .font(.system(size: 8.5, weight: .bold))
                    .foregroundStyle(.secondary)
            }
            .foregroundStyle(.primary)
            .padding(.horizontal, 11)
            .padding(.vertical, 5)
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .glassEffect(.regular.interactive(), in: .capsule)
    }
}

/// Model and effort for one bot, right in the toolbar.
struct ModelMenu: View {
    @Environment(PalStore.self) private var store
    let pal: Pal

    var body: some View {
        Menu {
            Section("Model") {
                ForEach(Models.all, id: \.id) { model in
                    Toggle(model.name, isOn: Binding(
                        get: { pal.model == model.id },
                        set: { if $0 { store.updateBot(pal.id, model: model.id) } }
                    ))
                }
            }
            Section("Effort") {
                ForEach(store.effortLevels, id: \.self) { level in
                    Toggle(Models.effortName(level), isOn: Binding(
                        get: { pal.effort == level },
                        set: { if $0 { store.updateBot(pal.id, effort: level) } }
                    ))
                }
            }
            Divider()
            Button("Use Team Defaults") { store.resetBotSettings(pal.id) }
        } label: {
            Label(Models.shortName(pal.model), systemImage: "cpu")
        }
        .menuIndicator(.hidden)
        .help("\(Models.name(pal.model)) · \(Models.effortName(pal.effort)) effort")
    }
}

/// Shown when the bots aren't signed in yet.
private struct SignInBanner: View {
    @Environment(PalStore.self) private var store
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        if let auth = store.auth, !auth.ok {
            HStack(spacing: 10) {
                Image(systemName: "person.crop.circle.badge.exclamationmark")
                    .font(.title3)
                    .foregroundStyle(Color.statusOrange)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Sign in so your team can answer").font(.callout.weight(.semibold))
                    Text("Open your desktop on Pal’s computer, open Terminal there, type claude login, and follow the steps.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                Button("Open Desktop") { openWindow(id: "display", value: "operator") }
                    .controlSize(.small)
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.statusOrange.opacity(0.1)))
            .padding(.horizontal, 20)
            // Clears the name pill that hangs over the top of the chat.
            .padding(.top, 30)
        }
    }
}

// MARK: - Messages

private struct MessageList: View {
    @Environment(PalStore.self) private var store
    let pal: Pal

    var body: some View {
        let messages = store.messages[pal.id] ?? []
        let items = Timeline.build(messages, palId: pal.id, work: store.work, team: store.teamMessages(of: pal.id))
        if items.isEmpty && !pal.status.isWorking {
            EmptyConversation(pal: pal)
        } else {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(items) { item in
                            switch item {
                            case .day(let date):
                                DaySeparator(date: date)
                            case .message(let row):
                                MessageRowView(row: row, pal: pal, highlighted: flashing == row.message.id)
                            case let .work(_, calls):
                                WorkGroupView(calls: calls, active: false)
                                    .padding(.vertical, 3)
                            case .team(_, let messages):
                                TeamExchangeView(messages: messages, palId: pal.id)
                                    .padding(.vertical, 3)
                            case .note(let message):
                                NoteView(message: message)
                            }
                        }
                        LiveTail(pal: pal)
                        Color.clear.frame(height: 1).id(Self.bottom)
                    }
                    // Full width: their messages at the left edge, yours at the right.
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, 20)
                    .padding(.top, 8)
                    .padding(.bottom, 6)
                }
                .scrollPosition($position)
                // Opens at the newest message (or where you left it), but a short
                // chat starts at the top.
                .defaultScrollAnchor(store.scrollSpots[pal.id] == nil ? .bottom : .top, for: .initialOffset)
                // Stays pinned to the newest message only while you're following it.
                .defaultScrollAnchor(following ? .bottom : nil, for: .sizeChanges)
                .defaultScrollAnchor(.top, for: .alignment)
                .onScrollPhaseChange { _, phase in scrollPhase = phase }
                // Growing content (a streaming reply) is followed only while you're
                // at the bottom; scrolling up lets it grow below you.
                .onScrollGeometryChange(for: ScrollSpot.self) { geometry in
                    // How far the view is above its furthest scroll position.
                    ScrollSpot(
                        contentHeight: geometry.contentSize.height,
                        offset: geometry.contentOffset.y,
                        fromBottom: geometry.contentSize.height + geometry.contentInsets.bottom
                            - geometry.visibleRect.height - geometry.contentOffset.y
                    )
                } action: { old, new in
                    if new.contentHeight != old.contentHeight {
                        if following { proxy.scrollTo(Self.bottom, anchor: .bottom) }
                    } else if settled && scrollPhase != .animating {
                        following = new.fromBottom < 40
                    }
                    // Remembers where you are, unless it's the newest message.
                    if settled {
                        store.scrollSpots[pal.id] = following ? nil : new.offset
                    }
                }
                .overlay(alignment: .bottom) {
                    if !following {
                        JumpToBottomButton {
                            following = true
                            scrollToBottom(proxy, animated: true)
                        }
                        .padding(.bottom, 12)
                        .transition(.offset(y: 56).combined(with: .opacity).combined(with: .scale(scale: 0.7)))
                    }
                }
                .animation(.spring(response: 0.42, dampingFraction: 0.78), value: following)
                .task {
                    // Opens where you left this chat, or at the newest message.
                    // Layout can still be settling, so land there twice before
                    // tracking where you scroll.
                    let spot = store.scrollSpots[pal.id]
                    if spot != nil { following = false }
                    for pause in [0.35, 0.1] {
                        if let spot { position.scrollTo(y: spot) } else { scrollToBottom(proxy, animated: false) }
                        try? await Task.sleep(for: .seconds(pause))
                    }
                    settled = true
                }
                .onChange(of: store.focusedMessage[pal.id], initial: true) { _, id in
                    guard let id else { return }
                    store.focusedMessage[pal.id] = nil
                    reveal(id, proxy)
                }
                .onChange(of: messages.last?.id) { old, _ in
                    // Your own message always brings you down; a bot's only if you were there.
                    guard following || messages.last?.sender == "user" else { return }
                    following = true
                    scrollToBottom(proxy, animated: old != nil)
                }
            }
        }
    }

    @State private var following = true
    /// A message being pointed out, outlined for a moment.
    @State private var flashing: String?
    @State private var position = ScrollPosition()
    /// False until the opening scroll lands, so its layout passes don't count as you scrolling.
    @State private var settled = false
    @State private var scrollPhase: ScrollPhase = .idle

    private struct ScrollSpot: Equatable {
        let contentHeight: CGFloat
        let offset: CGFloat
        let fromBottom: CGFloat
    }

    private static let bottom = "bottom"

    /// Brings a message into view and outlines it briefly.
    private func reveal(_ id: String, _ proxy: ScrollViewProxy) {
        Task {
            // A chat that just opened is still landing at its newest message.
            if !settled { try? await Task.sleep(for: .seconds(0.5)) }
            following = false
            withAnimation(.smooth(duration: 0.4)) { proxy.scrollTo(id, anchor: .center) }
            withAnimation(.easeOut(duration: 0.2)) { flashing = id }
            try? await Task.sleep(for: .seconds(1.4))
            withAnimation(.easeOut(duration: 0.5)) { if flashing == id { flashing = nil } }
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy, animated: Bool) {
        Task {
            await Task.yield()
            if animated {
                withAnimation(.smooth(duration: 0.45)) { proxy.scrollTo(Self.bottom, anchor: .bottom) }
            } else {
                proxy.scrollTo(Self.bottom, anchor: .bottom)
            }
        }
    }
}

/// Floats above the composer when you've scrolled up; takes you back to the newest message.
private struct JumpToBottomButton: View {
    let action: () -> Void

    var body: some View {
        // Built like a toolbar button: a plain icon on the toolbar's glass, so
        // it matches the sidebar button instead of taking the accent color.
        Button(action: action) {
            Label("Scroll to Newest", systemImage: "arrow.down")
                .labelStyle(.iconOnly)
        }
        .buttonStyle(ToolbarLikeButtonStyle())
        .help("Scroll to the newest message")
    }
}

/// A round glass button that responds like the toolbar's: a soft highlight on
/// hover, darker while pressed, and no bounce.
private struct ToolbarLikeButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        Face(configuration: configuration)
    }

    private struct Face: View {
        let configuration: Configuration
        @State private var hovering = false

        var body: some View {
            configuration.label
                .font(.system(size: 14))
                .foregroundStyle(.primary)
                .frame(width: 34, height: 34)
                .background {
                    Circle().fill(Color.primary.opacity(configuration.isPressed ? 0.16 : hovering ? 0.07 : 0))
                }
                .contentShape(Circle())
                .glassEffect(.regular, in: .circle)
                .onHover { hovering = $0 }
                .animation(.easeOut(duration: 0.12), value: hovering)
                .animation(.easeOut(duration: 0.08), value: configuration.isPressed)
        }
    }
}

/// What the bot is doing right now: tool steps, thinking, streaming text.
private struct LiveTail: View {
    @Environment(PalStore.self) private var store
    let pal: Pal

    var body: some View {
        let text = store.streaming[pal.id] ?? ""
        let calls = store.liveTools[pal.id] ?? []
        if pal.status.isWorking {
            VStack(alignment: .leading, spacing: 6) {
                if case .waiting(let mate) = pal.status {
                    Label("Waiting on \(store.name(of: mate))", systemImage: "hourglass")
                        .font(.system(size: 11.5, weight: .medium))
                        .foregroundStyle(.secondary)
                }
                if !calls.isEmpty {
                    WorkGroupView(calls: calls, active: true)
                }
                if let thought = store.thinking[pal.id], text.isEmpty {
                    Text(thought.previewLine)
                        .font(.system(size: 11.5).italic())
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .padding(.leading, 4)
                }
                HStack(alignment: .top, spacing: 0) {
                    if text.isEmpty {
                        TypingIndicator()
                    } else {
                        RichText(text: text)
                            .bubble(outgoing: false, first: false, last: true)
                    }
                    Spacer(minLength: 80)
                }
            }
            .padding(.top, 4)
            .transition(.opacity)
        }
    }
}

private struct EmptyConversation: View {
    let pal: Pal

    var body: some View {
        VStack(spacing: 10) {
            AvatarView(pal: pal, size: 64)
            Text(pal.name)
                .font(.title2.weight(.semibold))
            Text(pal.role.isEmpty ? "Send a message to get started." : "\(pal.role) · Send a message to get started.")
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct DaySeparator: View {
    let date: Date

    var body: some View {
        Text(Fmt.day(date))
            .font(.system(size: 11, weight: .semibold))
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity)
            .padding(.top, 18)
            .padding(.bottom, 6)
    }
}

private struct NoteView: View {
    let message: Message

    var body: some View {
        Label(message.content, systemImage: "exclamationmark.triangle.fill")
            .font(.system(size: 11.5))
            .foregroundStyle(Color.statusRed)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
    }
}

/// Three dots that step a few times a second. Deliberately not a continuous
/// animation: those redraw every frame and keep the main thread busy.
struct TypingIndicator: View {
    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.35)) { context in
            let step = Int(context.date.timeIntervalSinceReferenceDate / 0.35) % 3
            HStack(spacing: 4) {
                ForEach(0..<3, id: \.self) { i in
                    Circle()
                        .fill(Color.secondary.opacity(i == step ? 0.9 : 0.35))
                        .frame(width: 6, height: 6)
                }
            }
            .frame(height: 16)
            .bubble(outgoing: false, first: true, last: true)
        }
    }
}
