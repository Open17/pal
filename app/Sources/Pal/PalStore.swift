import AppKit
import SwiftUI

/// What's selected in the sidebar.
enum SidebarItem: Hashable {
    case memory
    case computer
    case pal(String)

    /// Saved between launches so Pal reopens where you left off.
    var storageKey: String {
        switch self {
        case .memory: "memory"
        case .computer: "computer"
        case .pal(let id): "pal:\(id)"
        }
    }

    init?(storageKey: String) {
        switch storageKey {
        case "memory": self = .memory
        case "computer": self = .computer
        case let key where key.hasPrefix("pal:"): self = .pal(String(key.dropFirst("pal:".count)))
        default: return nil
        }
    }
}

enum Connection: Equatable {
    case connecting, online, offline(String)
}

enum SheetRoute: Identifiable {
    case botSettings(Pal)
    case newMemory(scope: String)
    case newBot
    /// A read-only look at two bots' conversation, opened from a chat.
    case thread(id: String, focus: String?)

    var id: String {
        switch self {
        case .botSettings(let p): "bot-\(p.id)"
        case .newMemory(let scope): "memory-\(scope)"
        case .newBot: "new-bot"
        case .thread(let id, _): "thread-\(id)"
        }
    }
}

/// Everything the app shows, kept in sync with the runtime's event stream.
@Observable
final class PalStore {
    let vm = VMController()

    var connection: Connection = .connecting {
        didSet {
            // Without the runtime nothing is answering, whatever the bots last reported.
            guard connection != .online else { return }
            for i in pals.indices where pals[i].rawStatus != "offline" || pals[i].waitingOn != nil {
                pals[i].rawStatus = "offline"
                pals[i].waitingOn = nil
            }
        }
    }
    /// True once the runtime has answered, so a brief disconnect doesn't blank the app.
    var hasConnected = false
    /// Set once every chat's history has loaded; until then the launch screen shows.
    var isReady = false
    @ObservationIgnored private(set) var readyAt: Date?
    @ObservationIgnored private let launchedAt = Date.now

    var pals: [Pal] = []
    var displays: [Display] = []
    var auth: AuthInfo? {
        didSet { syncSignIn() }
    }
    var defaults: ModelDefaults?
    var effortLevels = ["low", "medium", "high", "xhigh", "max"]

    /// Your conversation with each bot, by bot id.
    var messages: [String: [Message]] = [:]
    /// Conversations between bots, newest first.
    var teamConversations: [ConversationSummary] = []
    var teamMessages: [String: [Message]] = [:]
    /// Text a bot is writing right now, before its reply is recorded.
    var streaming: [String: String] = [:]
    /// What a bot is thinking about right now (a summary).
    var thinking: [String: String] = [:]
    /// Tool calls in a bot's current turn.
    var liveTools: [String: [ToolCall]] = [:]
    /// Tool calls that led to a recorded reply, by message id (this session only).
    var work: [String: [ToolCall]] = [:]
    var unread: [String: Int] = [:]
    var drafts: [String: String] = [:]
    /// Where you left each chat scrolled up, by bot id, until the app quits.
    /// No entry means you were at the newest message, and it opens there.
    @ObservationIgnored var scrollSpots: [String: CGFloat] = [:]

    var sharedMemory: [MemoryEntry] = []
    var botMemory: [String: [MemoryEntry]] = [:]

    var selection: SidebarItem? {
        didSet {
            markSelectedRead()
            UserDefaults.standard.set(selection?.storageKey, forKey: "lastSelection")
        }
    }
    var sheet: SheetRoute?
    var sidebarCollapsed = false
    var toast: String?

    @ObservationIgnored private(set) var client = PalClient.fromDefaults()
    @ObservationIgnored private var loop: Task<Void, Never>?
    @ObservationIgnored private var statusLoop: Task<Void, Never>?
    @ObservationIgnored private var toastTask: Task<Void, Never>?

    // MARK: - Derived

    var sortedPals: [Pal] {
        pals.sorted { lastActivity($0) > lastActivity($1) }
    }

    var selectedId: String? {
        if case .pal(let id) = selection { id } else { nil }
    }

    var selectedPal: Pal? {
        selectedId.flatMap(pal)
    }

    var badgeCount: Int {
        unread.values.reduce(0, +)
    }

    func pal(_ id: String) -> Pal? {
        pals.first { $0.id == id }
    }

    func display(for owner: String) -> Display? {
        displays.first { $0.owner == owner }
    }

    func name(of participant: String) -> String {
        switch participant {
        case "user": "You"
        default: pal(participant)?.name ?? participant.capitalized
        }
    }

    /// What to call a display: yours or a bot's computer.
    func displayTitle(_ owner: String) -> String {
        switch owner {
        case "operator": "Your display"
        default: "\(name(of: owner))’s computer"
        }
    }

    func lastMessage(_ palId: String) -> Message? {
        messages[palId]?.last
    }

    func lastActivity(_ pal: Pal) -> Date {
        lastMessage(pal.id)?.createdAt ?? .distantPast
    }

    // MARK: - Connection

    func start() {
        vm.startPolling()
        guard loop == nil else { return }
        loop = Task { await run() }
        statusLoop = Task {
            // Sign-in can change at any time (e.g. `claude login` in the VM).
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(15))
                await refreshStatus()
            }
        }
    }

    /// Bots can't answer while Claude is signed out; mark them so their status says so.
    private func syncSignIn() {
        let signedIn = auth?.ok ?? true
        for i in pals.indices where pals[i].signedIn != signedIn {
            pals[i].signedIn = signedIn
        }
    }

    /// Re-reads sign-in, bots, and displays from the runtime.
    func refreshStatus() async {
        guard connection == .online, let status: RuntimeStatus = try? await client.get("/v1/status") else { return }
        auth = status.auth
        displays = status.displays
        // Bots come and go while Pal runs: take the runtime's list, keeping
        // what only events tell us.
        pals = status.bots.map { bot in
            var bot = bot
            bot.waitingOn = pals.first { $0.id == bot.id }?.waitingOn
            return bot
        }
        syncSignIn()
        if let selected = selectedId, pal(selected) == nil {
            selection = pals.first.map { .pal($0.id) }
        }
    }

    /// Add a bot to the team, and open its conversation.
    func createBot(name: String, role: String, persona: String, color: String) async throws {
        struct Body: Encodable { let name, role, persona, color: String }
        let created: Pal = try await client.post("/v1/bots", Body(name: name, role: role, persona: persona, color: color))
        await refreshStatus()
        open(created.id)
    }

    func removeBot(_ id: String) {
        perform { [self] in
            try await client.run("DELETE", "/v1/bots/\(id)")
            await refreshStatus()
        }
    }

    func reconnect() {
        loop?.cancel()
        loop = nil
        client = .fromDefaults()
        connection = .connecting
        start()
    }

    private func run() async {
        while !Task.isCancelled {
            guard vm.isRunning else {
                connection = .offline("Pal's computer is off.")
                try? await Task.sleep(for: .seconds(1))
                continue
            }
            client = .fromDefaults()
            let socket = client.eventsTask()
            socket.resume()
            do {
                while !Task.isCancelled {
                    let message = try await withTaskCancellationHandler {
                        try await socket.receive()
                    } onCancel: {
                        socket.cancel(with: .goingAway, reason: nil)
                    }
                    let data: Data
                    switch message {
                    case .string(let s): data = Data(s.utf8)
                    case .data(let d): data = d
                    @unknown default: continue
                    }
                    do {
                        try await handle(client.decodeEvent(data))
                    } catch {
                        print("[pal] couldn't read event:", error)
                    }
                }
            } catch {
                socket.cancel(with: .goingAway, reason: nil)
                if !Task.isCancelled {
                    connection = .offline(hasConnected ? "Reconnecting…" : "Waiting for Pal to start…")
                }
            }
            try? await Task.sleep(for: .seconds(hasConnected ? 2 : 1))
        }
    }

    /// Loads everything after (re)connecting; the event stream keeps it current.
    private func loadSnapshot() async {
        do {
            let status: RuntimeStatus = try await client.get("/v1/status")
            pals = status.bots
            syncSignIn()
            displays = status.displays
            auth = status.auth
            if let settings: SettingsInfo = try? await client.get("/v1/settings") {
                defaults = settings.defaults
                effortLevels = settings.effortLevels
            }
            connection = .online
            hasConnected = true
            if selection == nil, let saved = UserDefaults.standard.string(forKey: "lastSelection") {
                selection = SidebarItem(storageKey: saved)
            }
            if selection == nil || (selectedId != nil && selectedPal == nil) {
                selection = pals.first.map { .pal($0.id) }
            }
            await loadHistories()
            await loadTeamConversations()
            await loadTeamMessages()
            await loadMemory()
            await becomeReady()
        } catch {
            connection = .offline(error.localizedDescription)
        }
    }

    private func handle(_ event: ServerEvent) async {
        switch event {
        case .hello:
            await loadSnapshot()
        case .messageCreated(let message):
            receive(message)
        case let .botStatus(bot, status, queued, waitingOn):
            guard let i = pals.firstIndex(where: { $0.id == bot }) else { return }
            pals[i].rawStatus = status
            pals[i].queued = queued
            pals[i].waitingOn = waitingOn
            if status != "busy" {
                streaming[bot] = nil
                thinking[bot] = nil
            }
        case let .textDelta(bot, text):
            thinking[bot] = nil
            streaming[bot, default: ""] += text
        case let .thinking(bot, text):
            thinking[bot] = text
        case let .toolStarted(bot, id, tool, input):
            // The reply is the text after the last tool call, so start the live bubble over.
            streaming[bot] = nil
            liveTools[bot, default: []].append(ToolCall(id: id, tool: tool, input: input))
        case let .toolFinished(bot, id, isError):
            if let i = liveTools[bot]?.firstIndex(where: { $0.id == id }) {
                liveTools[bot]?[i].finished = true
                liveTools[bot]?[i].failed = isError
            }
        case let .turnCompleted(bot, _):
            streaming[bot] = nil
            thinking[bot] = nil
            liveTools[bot] = nil
        case let .settingsChanged(bot, model, effort):
            if let i = pals.firstIndex(where: { $0.id == bot }) {
                pals[i].model = model
                pals[i].effort = effort
            }
        case let .botUpdated(bot, color):
            if let i = pals.firstIndex(where: { $0.id == bot }) { pals[i].color = color }
        case .botAdded, .botRemoved:
            await refreshStatus()
        case .display(let display):
            if let i = displays.firstIndex(where: { $0.owner == display.owner }) {
                displays[i] = display
            } else {
                displays.append(display)
            }
        case .unknown:
            break
        }
    }

    private func receive(_ message: Message) {
        // A bot's reply carries the tool calls of the turn that produced it.
        if pal(message.sender) != nil, message.replyTo != nil, let calls = liveTools[message.sender], !calls.isEmpty {
            work[message.id] = calls
            liveTools[message.sender] = nil
        }
        if message.conversationId.hasPrefix("user--") {
            let bot = message.sender == "user" ? message.recipient : message.sender
            if messages[bot]?.contains(where: { $0.id == message.id }) == true { return }
            messages[bot, default: []].append(message)
            guard message.sender != "user" else { return }
            streaming[bot] = nil
            if !isViewing(bot) { unread[bot, default: 0] += 1 }
            if !NSApp.isActive, let pal = pal(bot) {
                Notifier.post(id: message.id, title: pal.name, body: message.content.previewLine, palId: bot)
            }
        } else {
            let id = message.conversationId
            if teamMessages[id]?.contains(where: { $0.id == message.id }) != true {
                teamMessages[id, default: []].append(message)
            }
            if let i = teamConversations.firstIndex(where: { $0.id == id }) {
                teamConversations[i].lastMessage = message
                teamConversations[i].messageCount += 1
                let updated = teamConversations.remove(at: i)
                teamConversations.insert(updated, at: 0)
            } else {
                let participants = id.components(separatedBy: "--")
                teamConversations.insert(
                    ConversationSummary(id: id, participants: participants, messageCount: 1, lastMessage: message),
                    at: 0
                )
            }
        }
    }

    private func becomeReady() async {
        guard !isReady else { return }
        // Let the launch screen settle rather than flash when everything loads at once.
        let shown = Date.now.timeIntervalSince(launchedAt)
        if shown < 1.2 { try? await Task.sleep(for: .seconds(1.2 - shown)) }
        readyAt = .now
        withAnimation(.smooth(duration: 0.55)) { isReady = true }
    }

    private func loadHistories() async {
        await withTaskGroup(of: (String, [Message]?).self) { group in
            for pal in pals {
                let client = client
                group.addTask {
                    struct Page: Decodable { let messages: [Message] }
                    let page: Page? = try? await client.get("/v1/conversations/user--\(pal.id)/messages?limit=300")
                    return (pal.id, page?.messages)
                }
            }
            for await (id, loaded) in group {
                guard let loaded else { continue }
                let ids = Set(loaded.map(\.id))
                let live = (messages[id] ?? []).filter { !ids.contains($0.id) }
                messages[id] = loaded + live
            }
        }
    }

    func loadTeamConversations() async {
        struct List: Decodable { let conversations: [ConversationSummary] }
        if let list: List = try? await client.get("/v1/conversations") {
            teamConversations = list.conversations.filter(\.isBetweenBots)
        }
    }

    /// Loads every conversation between bots, so each bot's chat can show
    /// what it said to its teammates.
    func loadTeamMessages() async {
        await withTaskGroup(of: (String, [Message]?).self) { group in
            for conversation in teamConversations {
                let client = client
                group.addTask {
                    struct Page: Decodable { let messages: [Message] }
                    let page: Page? = try? await client.get("/v1/conversations/\(conversation.id)/messages?limit=300")
                    return (conversation.id, page?.messages)
                }
            }
            for await (id, loaded) in group {
                guard let loaded else { continue }
                let ids = Set(loaded.map(\.id))
                let live = (teamMessages[id] ?? []).filter { !ids.contains($0.id) }
                teamMessages[id] = loaded + live
            }
        }
    }

    /// Messages between this bot and its teammates, oldest first.
    func teamMessages(of palId: String) -> [Message] {
        teamMessages
            .filter { $0.key.components(separatedBy: "--").contains(palId) }
            .values
            .joined()
            .sorted { $0.createdAt < $1.createdAt }
    }

    func loadTeamConversation(_ id: String) async {
        struct Page: Decodable { let messages: [Message] }
        if let page: Page = try? await client.get("/v1/conversations/\(id)/messages?limit=300") {
            teamMessages[id] = page.messages
        }
    }

    // MARK: - Navigation

    /// Hides or shows the sidebar instantly (see `SidebarSnap`).
    func setSidebarCollapsed(_ collapsed: Bool) {
        SidebarSnap.setCollapsed(collapsed)
        var transaction = Transaction(animation: nil)
        transaction.disablesAnimations = true
        withTransaction(transaction) { sidebarCollapsed = collapsed }
    }

    func open(_ palId: String) {
        selection = .pal(palId)
    }

    func isViewing(_ id: String) -> Bool {
        selectedId == id && NSApp.isActive
    }

    func markSelectedRead() {
        if let selectedId { unread[selectedId] = nil }
    }

    // MARK: - Chat

    func send(_ text: String, to id: String) {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        drafts[id] = nil
        Task {
            do {
                struct Sent: Decodable { let message: Message }
                let sent: Sent = try await client.post("/v1/bots/\(id)/messages", ["content": text])
                receive(sent.message)
            } catch {
                if (drafts[id] ?? "").isEmpty { drafts[id] = text }
                show(error)
            }
        }
    }

    func interrupt(_ id: String) {
        perform { try await self.client.run("POST", "/v1/bots/\(id)/interrupt") }
    }

    func resetSession(_ id: String) {
        perform {
            try await self.client.run("POST", "/v1/bots/\(id)/session/reset")
            self.show("\(self.name(of: id)) starts a fresh conversation next time.")
        }
    }

    // MARK: - Model settings

    func updateBot(_ id: String, model: String? = nil, effort: String? = nil, color: String? = nil) {
        struct Body: Encodable { let model, effort, color: String? }
        perform {
            let updated: Pal = try await self.client.patch("/v1/bots/\(id)", Body(model: model, effort: effort, color: color))
            self.apply(updated)
        }
    }

    func resetBotSettings(_ id: String) {
        perform {
            let updated: Pal = try await self.client.patch("/v1/bots/\(id)", ["reset": true])
            self.apply(updated)
        }
    }

    func updateDefaults(model: String? = nil, effort: String? = nil) {
        perform {
            let settings: SettingsInfo = try await self.client.patch("/v1/settings", ModelUpdate(model: model, effort: effort))
            self.defaults = settings.defaults
        }
    }

    private func apply(_ updated: Pal) {
        guard let i = pals.firstIndex(where: { $0.id == updated.id }) else { return }
        pals[i].model = updated.model
        pals[i].effort = updated.effort
        pals[i].color = updated.color
    }

    // MARK: - Displays

    func wake(_ owner: String) {
        perform { let _: Display = try await self.client.post("/v1/displays/\(owner)/wake") }
    }

    func sleep(_ owner: String) {
        perform { let _: Display = try await self.client.post("/v1/displays/\(owner)/sleep") }
    }

    func stopDisplay(_ owner: String) {
        perform { let _: Display = try await self.client.post("/v1/displays/\(owner)/stop") }
    }

    /// Where this Mac reaches a display's VNC server, via palvmd.
    func vncPort(for display: Display) -> Int {
        vm.hostPort(forGuestPort: display.vncPort) ?? display.vncPort
    }

    // MARK: - Memory

    func loadMemory() async {
        struct List: Decodable { let entries: [MemoryEntry] }
        if let list: List = try? await client.get("/v1/memory/shared") { sharedMemory = list.entries }
        for pal in pals {
            if let list: List = try? await client.get("/v1/memory/\(pal.id)") { botMemory[pal.id] = list.entries }
        }
    }

    func saveMemory(_ input: MemoryInput, scope: String) async throws {
        let _: MemoryEntry = try await client.post("/v1/memory/\(scope)", input)
        await loadMemory()
    }

    func deleteMemory(_ entry: MemoryEntry, scope: String) {
        perform {
            try await self.client.run("DELETE", "/v1/memory/\(scope)/\(entry.id)")
            await self.loadMemory()
        }
    }

    // MARK: - Errors

    private func perform(_ work: @escaping () async throws -> Void) {
        Task {
            do { try await work() } catch { show(error) }
        }
    }

    func show(_ error: any Error) {
        show(error.localizedDescription)
    }

    func show(_ message: String) {
        toast = message
        toastTask?.cancel()
        toastTask = Task {
            try? await Task.sleep(for: .seconds(4))
            if !Task.isCancelled { toast = nil }
        }
    }
}
