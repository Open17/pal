import AppKit
import SwiftUI

struct RootView: View {
    @Environment(PalStore.self) private var store
    /// Column visibility that snaps rather than slides (see `PalStore.setSidebarCollapsed`).
    private var columns: Binding<NavigationSplitViewVisibility> {
        Binding(
            get: { store.sidebarCollapsed ? .detailOnly : .all },
            set: { store.setSidebarCollapsed($0 == .detailOnly) }
        )
    }

    static let sidebarWidth: ClosedRange<CGFloat> = 220...380

    var body: some View {
        @Bindable var store = store
        Group {
            if store.isReady {
                NavigationSplitView(columnVisibility: columns) {
                    Sidebar()
                        .navigationSplitViewColumnWidth(min: Self.sidebarWidth.lowerBound, ideal: 290, max: Self.sidebarWidth.upperBound)
                        .toolbar(removing: .sidebarToggle)
                } detail: {
                    detail.loadIn(2)
                        .toolbar {
                            ToolbarItem(placement: .navigation) { SidebarButton() }
                        }
                }
                .transition(.opacity)
                .task(id: store.sidebarCollapsed) {
                    // Once the split view exists; again if showing the sidebar rebuilt it.
                    for delay in [0.0, 0.5] {
                        try? await Task.sleep(for: .seconds(delay))
                        SidebarSnap.limitWidth(min: Self.sidebarWidth.lowerBound, max: Self.sidebarWidth.upperBound)
                    }
                }
            } else {
                LaunchView()
                    .transition(.opacity.combined(with: .scale(scale: 1.06)))
            }
        }
        .overlay(alignment: .bottom) { toast }
        .animation(.spring(duration: 0.35), value: store.toast)
        .sheet(item: $store.sheet) { route in
            switch route {
            case .botSettings(let pal): BotSettingsSheet(pal: pal)
            case .newMemory(let scope): NewMemorySheet(scope: scope)
            case .newBot: NewBotSheet()
            case let .thread(id, focus): TeamThreadSheet(id: id, focus: focus)
            }
        }
        .tint(.palAccent)
        .frame(minWidth: 900, minHeight: 560)
        .task { store.start() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            store.markSelectedRead()
            Task { await store.refreshStatus() }
        }
        .onChange(of: store.badgeCount, initial: true) { _, count in
            NSApp.dockTile.badgeLabel = count > 0 ? "\(count)" : nil
        }
    }

    @ViewBuilder
    private var detail: some View {
        switch store.selection {
        case .memory:
            MemoryView()
        case .computer:
            ComputerView()
        case .pal(let id):
            if let pal = store.pal(id) {
                ConversationView(pal: pal)
                    .id(id)
            } else {
                NoSelectionView()
            }
        case nil:
            if store.pals.isEmpty { EmptyTeamView() } else { NoSelectionView() }
        }
    }

    @ViewBuilder
    private var toast: some View {
        if let message = store.toast {
            Text(message)
                .font(.callout)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .glassEffect()
                .padding(.bottom, 84)
                .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }
}

// MARK: - Sidebar

/// Hides and shows the sidebar. It sits at the top of the main view, just
/// right of the sidebar, in place of the system toggle inside the sidebar.
private struct SidebarButton: View {
    @Environment(PalStore.self) private var store

    var body: some View {
        Button(store.sidebarCollapsed ? "Show Sidebar" : "Hide Sidebar", systemImage: "sidebar.left") {
            store.setSidebarCollapsed(!store.sidebarCollapsed)
        }
        .help(store.sidebarCollapsed ? "Show the sidebar (⌃⌘S)" : "Hide the sidebar (⌃⌘S)")
    }
}

private struct Sidebar: View {
    @Environment(PalStore.self) private var store
    @State private var removing: Pal?

    var body: some View {
        List {
            Section("Team") {
                ForEach(Array(store.sortedPals.enumerated()), id: \.element.id) { index, pal in
                    PalRow(pal: pal, selected: store.selectedId == pal.id)
                        .sidebarRow(.pal(pal.id), index: index)
                        .contextMenu {
                            Button("Bot Settings…") { store.sheet = .botSettings(pal) }
                            Divider()
                            Button("New Conversation") { store.resetSession(pal.id) }
                            Divider()
                            Button("Remove \(pal.name)…", role: .destructive) { removing = pal }
                                .disabled(store.pals.count <= 1)
                        }
                }
                if store.pals.isEmpty {
                    Text("No bots yet")
                        .foregroundStyle(.secondary)
                }
            }
        }
        .listStyle(.sidebar)
        .tint(.palAccent)
        .toolbar {
            // In the sidebar's part of the toolbar, pushed to its top right.
            ToolbarSpacer(.flexible)
            ToolbarItem {
                Button("Search", systemImage: "magnifyingglass") { SearchPanel.shared.toggle(store: store) }
                    .help("Search bots, messages, and memory (⌘K)")
            }
            ToolbarItem {
                Button("New Bot", systemImage: "plus") { store.sheet = .newBot }
                    .help("Add a bot to the team")
            }
        }
        .confirmationDialog(
            "Remove \(removing?.name ?? "this bot") from the team?",
            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
            presenting: removing
        ) { pal in
            Button("Remove \(pal.name)", role: .destructive) { store.removeBot(pal.id) }
        } message: { pal in
            Text("\(pal.name) stops and their display closes. Their memories and your conversation history are kept.")
        }
        .safeAreaInset(edge: .bottom, spacing: 0) { SidebarFooter() }
    }
}

private struct PalRow: View {
    @Environment(PalStore.self) private var store
    let pal: Pal
    let selected: Bool

    var body: some View {
        let unread = store.unread[pal.id] ?? 0
        let last = store.lastMessage(pal.id)
        HStack(spacing: 10) {
            AvatarView(pal: pal, size: 34, showStatus: true)
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(pal.name)
                        .font(.system(size: 13, weight: unread > 0 ? .bold : .semibold))
                        .lineLimit(1)
                    Spacer(minLength: 4)
                    if let last {
                        Text(Fmt.listTime(last.createdAt))
                            .font(.system(size: 11))
                            .foregroundStyle(selected ? AnyShapeStyle(.white.opacity(0.85)) : AnyShapeStyle(.secondary))
                    }
                }
                HStack(spacing: 6) {
                    preview(last)
                        .font(.system(size: 12))
                        .foregroundStyle(selected ? AnyShapeStyle(.white.opacity(0.85)) : AnyShapeStyle(.secondary))
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    if unread > 0 {
                        Text("\(unread)")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundStyle(.white)
                            .padding(.horizontal, 5)
                            .frame(minWidth: 17, minHeight: 17)
                            .background(Capsule().fill(selected ? Color.white.opacity(0.3) : Color.palAccent))
                    }
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func preview(_ last: Message?) -> Text {
        switch pal.status {
        case .waiting(let mate):
            return Text("\(Image(systemName: "hourglass")) Waiting on \(store.name(of: mate))")
        case .busy:
            return Text((store.streaming[pal.id] ?? "").isEmpty ? "Working…" : "Typing…")
        default:
            guard let last else { return Text(pal.role.isEmpty ? "No messages yet" : pal.role) }
            if last.isError { return Text("\(Image(systemName: "exclamationmark.triangle")) \(last.content.previewLine)") }
            return Text(last.sender == "user" ? "You: \(last.content.previewLine)" : last.content.previewLine)
        }
    }
}

/// A sidebar row. It's selected when the click is released on it, like a
/// button, rather than on press. The selection color is drawn by hand because
/// the system highlight turns grey whenever the sidebar isn't focused.
private struct SidebarRow: ViewModifier {
    @Environment(PalStore.self) private var store
    let item: SidebarItem
    /// Orders the row's load-in at launch (see `LoadIn`).
    let index: Int

    func body(content: Content) -> some View {
        let selected = store.selection == item
        content
            .foregroundStyle(selected ? Color.white : Color.primary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .onTapGesture { store.selection = item }
            // The selected row skips the launch cascade and arrives with the
            // window, so its highlight is never empty.
            .loadIn(selected ? nil : index)
            .listRowBackground(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(selected ? Color.palAccent : .clear)
                    .padding(.horizontal, 10)
            )
    }
}

private extension View {
    func sidebarRow(_ item: SidebarItem, index: Int) -> some View {
        modifier(SidebarRow(item: item, index: index))
    }
}

/// Pal's computer and sign-in, pinned to the bottom of the sidebar.
private struct SidebarFooter: View {
    @Environment(PalStore.self) private var store
    @State private var showing = false

    var body: some View {
        Button { showing.toggle() } label: {
            HStack(spacing: 9) {
                Image(systemName: "desktopcomputer")
                    .font(.system(size: 14))
                    .foregroundStyle(store.vm.isRunning ? Color.statusGreen : .secondary)
                    .frame(width: 18, height: 18)
                VStack(alignment: .leading, spacing: 0) {
                    Text("Pal’s computer")
                        .font(.system(size: 12, weight: .medium))
                    Text(summary)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("Pal’s computer")
        .popover(isPresented: $showing, arrowEdge: .top) {
            ComputerPopover().environment(store)
        }
    }

    private var summary: String {
        switch store.vm.power {
        case .running:
            if store.connection != .online { return "Starting the team…" }
            return store.auth?.ok == false ? "On · not signed in" : "On"
        case .starting: return "Turning on…"
        case .stopping: return "Shutting down…"
        case .off: return "Off"
        case .notInstalled: return "Not set up"
        case .unknown: return "Checking…"
        }
    }
}

struct ComputerPopover: View {
    @Environment(PalStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openSettings) private var openSettings
    @State private var confirmOff = false

    var body: some View {
        let vm = store.vm
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Pal’s computer").font(.headline)
                Spacer()
                PowerButton(confirmOff: $confirmOff)
            }
            Text("A private Debian computer where your team works. It has the internet but can’t reach this Mac or your network.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if case .notInstalled(let hint) = vm.power {
                Label(hint, systemImage: "wrench.and.screwdriver").font(.callout)
            }
            if let problem = vm.problem {
                Label(problem, systemImage: "exclamationmark.triangle.fill")
                    .font(.callout)
                    .foregroundStyle(Color.statusRed)
            }
            if vm.isRunning {
                Divider()
                if let auth = store.auth {
                    Label(auth.ok ? "Signed in (\(auth.method))" : "Not signed in", systemImage: auth.ok ? "checkmark.seal.fill" : "person.crop.circle.badge.exclamationmark")
                        .foregroundStyle(auth.ok ? Color.statusGreen : Color.statusOrange)
                        .font(.callout)
                }
                if let since = vm.startedAt {
                    Text("On since \(Fmt.relative(since).lowercased())").font(.caption).foregroundStyle(.secondary)
                }
            }
            Divider()
            HStack(spacing: 6) {
                Circle().fill(store.connection == .online ? Color.statusGreen : .secondary).frame(width: 7, height: 7)
                Text(store.connection == .online ? "Connected to \(store.client.displayAddress)" : "Team not connected")
                Spacer()
                Button("Log") { NSWorkspace.shared.open(vm.log) }.buttonStyle(.link)
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            Divider()
            Button {
                dismiss()
                openSettings()
            } label: {
                Label("Settings…", systemImage: "gearshape")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .padding(16)
        .frame(width: 320)
        .confirmationDialog("Turn off Pal’s computer?", isPresented: $confirmOff) {
            Button("Turn Off", role: .destructive) { store.vm.turnOff() }
        } message: {
            Text("Your team stops working until you turn it back on. Open windows on their displays are closed.")
        }
    }
}

/// On/off for Pal's computer.
struct PowerButton: View {
    @Environment(PalStore.self) private var store
    @Binding var confirmOff: Bool

    var body: some View {
        switch store.vm.power {
        case .running:
            Button("Turn Off", systemImage: "power") { confirmOff = true }
        case .off:
            Button("Turn On", systemImage: "power") { store.vm.turnOn() }
                .buttonStyle(.borderedProminent)
        case .starting, .stopping, .unknown:
            ProgressView().controlSize(.small)
        case .notInstalled:
            EmptyView()
        }
    }
}

// MARK: - Placeholders

private struct NoSelectionView: View {
    var body: some View {
        ContentUnavailableView("No Conversation Selected", systemImage: "bubble.left.and.bubble.right", description: Text("Choose a bot in the sidebar."))
    }
}

struct EmptyTeamView: View {
    var body: some View {
        ContentUnavailableView {
            Label("No Bots Yet", systemImage: "person.2")
        } description: {
            Text("Bots are defined in ~/.config/pal/bots inside Pal’s computer.")
        }
    }
}

/// Shown while Pal starts: the app's mark, faint and centered like a watermark.
/// Drawn in the text color at low opacity, so it suits light and dark mode alike.
private struct LaunchView: View {
    @Environment(PalStore.self) private var store
    @State private var shown = false
    @State private var apart = false

    var body: some View {
        VStack(spacing: 22) {
            LaunchMark(apart: apart)
                .scaleEffect(shown ? 1 : 0.85)
                .opacity(shown ? 1 : 0)
            LaunchStatus()
                .frame(maxWidth: 380)
                .transition(.opacity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .animation(.smooth, value: store.vm.power)
        // A bare window: no title and no toolbar hairline.
        .toolbar(removing: .title)
        .toolbarBackgroundVisibility(.hidden, for: .windowToolbar)
        .task {
            withAnimation(.smooth(duration: 0.35)) { shown = true }
            try? await Task.sleep(for: .seconds(0.3))
            // The bubbles tip away from each other, then click back into place.
            // Only runs while this screen is up, before any chats load.
            while !Task.isCancelled {
                withAnimation(.easeOut(duration: 0.26)) { apart = true }
                try? await Task.sleep(for: .seconds(0.26))
                withAnimation(.spring(response: 0.26, dampingFraction: 0.7)) { apart = false }
                try? await Task.sleep(for: .seconds(1.2))
            }
        }
    }
}

/// What's keeping the team from appearing: the computer is off, starting, or not set up.
private struct LaunchStatus: View {
    @Environment(PalStore.self) private var store
    @State private var confirmOff = false

    var body: some View {
        VStack(spacing: 10) {
            switch store.vm.power {
            case .off:
                Text("Pal’s computer is off.").foregroundStyle(.secondary)
                PowerButton(confirmOff: $confirmOff).controlSize(.large)
            case .starting:
                Text("Turning on Pal’s computer…").foregroundStyle(.secondary)
            case .running where store.hasConnected == false:
                Text("Waiting for your team to start…").foregroundStyle(.secondary)
            case .notInstalled(let hint):
                Text("Pal’s computer isn’t set up yet.").font(.headline)
                Text(hint).foregroundStyle(.secondary)
            default:
                EmptyView()
            }
            if let problem = store.vm.problem {
                Text(problem).font(.callout).foregroundStyle(Color.statusRed)
            }
        }
        .font(.callout)
        .multilineTextAlignment(.center)
    }
}

/// The app's mark as two separate bubbles, so they can move on their own.
private struct LaunchMark: View {
    let apart: Bool

    var body: some View {
        ZStack {
            back
            // Cut a thin gap around the front bubble, as in the app icon.
            ForEach(0..<8, id: \.self) { i in
                let angle = Double(i) * .pi / 4
                front.offset(x: 4 * cos(angle), y: 4 * sin(angle))
            }
            .blendMode(.destinationOut)
            front
        }
        .compositingGroup()
        .foregroundStyle(.primary)
        .opacity(0.1)
        .frame(width: 120, height: 110)
    }

    // Each bubble pivots on its tail, so they tip away from each other.
    private var back: some View {
        Image(systemName: "bubble.left.fill")
            .font(.system(size: 62, weight: .semibold))
            .rotationEffect(.degrees(apart ? -9 : 0), anchor: .bottomLeading)
            .offset(x: -18, y: -14)
    }

    private var front: some View {
        Image(systemName: "bubble.right.fill")
            .font(.system(size: 62, weight: .semibold))
            .rotationEffect(.degrees(apart ? 9 : 0), anchor: .bottomTrailing)
            .offset(x: 18, y: 14)
    }
}

/// Eases sidebar rows in one after another the first time Pal shows its chats.
private struct LoadIn: ViewModifier {
    @Environment(PalStore.self) private var store
    /// Where the view falls in the cascade; nil shows it right away.
    let index: Int?
    @State private var shown = false

    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown ? 0 : 8)
            .onAppear {
                // Only right after launch; rows that appear later (search, new pals) just show.
                guard let index, let readyAt = store.readyAt, Date.now.timeIntervalSince(readyAt) < 1 else {
                    shown = true
                    return
                }
                withAnimation(.smooth(duration: 0.45).delay(0.12 + Double(min(index, 12)) * 0.04)) { shown = true }
            }
    }
}

private extension View {
    func loadIn(_ index: Int?) -> some View {
        modifier(LoadIn(index: index))
    }
}
