import AppKit
import SwiftUI
import UserNotifications

@main
struct PalApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var store = PalStore()
    @AppStorage("showInspector") private var showInspector = false

    var body: some Scene {
        Window("Pal", id: "main") {
            RootView()
                .environment(store)
                .onAppear { appDelegate.store = store }
        }
        .windowToolbarStyle(.unified)
        .defaultSize(width: 1180, height: 760)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandGroup(replacing: .sidebar) {
                Button(store.sidebarCollapsed ? "Show Sidebar" : "Hide Sidebar") {
                    store.setSidebarCollapsed(!store.sidebarCollapsed)
                }
                .keyboardShortcut("s", modifiers: [.control, .command])
            }
            CommandMenu("Go") {
                Button("Search…") { SearchPanel.shared.toggle(store: store) }
                    .keyboardShortcut("k")
                Divider()
                Button("Memory") { store.selection = .memory }
                    .keyboardShortcut("1")
                Button("Computer") { store.selection = .computer }
                    .keyboardShortcut("2")
                Divider()
                Button("Next in Sidebar") { store.selectAdjacent(1) }
                    .keyboardShortcut(.tab, modifiers: .control)
                Button("Previous in Sidebar") { store.selectAdjacent(-1) }
                    .keyboardShortcut(.tab, modifiers: [.control, .shift])
                Divider()
                // In team order, so a bot keeps its shortcut when the sidebar reorders.
                ForEach(Array(store.pals.prefix(9).enumerated()), id: \.element.id) { index, pal in
                    Button(pal.name) { store.open(pal.id) }
                        .keyboardShortcut(KeyEquivalent(Character("\(index + 1)")), modifiers: [.command, .option])
                }
            }
            CommandMenu("Bot") {
                Button("Stop") { store.selectedId.map(store.interrupt) }
                    .keyboardShortcut(".")
                    .disabled(!(store.selectedPal?.status.isWorking ?? false))
                Button(showInspector ? "Hide Details" : "Show Details") { showInspector.toggle() }
                    .keyboardShortcut("i")
                    .disabled(store.selectedPal == nil)
                Button(store.selectedPal.map { store.displayOpen.contains($0.id) } == true ? "Hide Computer" : "Show Computer") {
                    if let pal = store.selectedPal { store.setDisplayOpen(!store.displayOpen.contains(pal.id), for: pal.id) }
                }
                .keyboardShortcut("d", modifiers: [.command, .option])
                .disabled(store.selectedPal == nil)
                Divider()
                Button("Bot Settings…") { store.selectedPal.map { store.sheet = .botSettings($0) } }
                    .keyboardShortcut("e")
                    .disabled(store.selectedPal == nil)
            }
            CommandMenu("Computer") {
                Button("Turn On") { store.vm.turnOn() }
                    .disabled(store.vm.power != .off)
                Button("Turn Off") { store.vm.turnOff() }
                    .disabled(!store.vm.isRunning)
            }
        }

        WindowGroup("Display", id: "display", for: String.self) { $owner in
            if let owner {
                DisplayWindow(owner: owner).environment(store)
            }
        }
        .defaultSize(width: 1280, height: 840)

        Settings {
            SettingsView()
                .environment(store)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    var store: PalStore?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Needed when launched with `swift run`, which has no app bundle.
        NSApp.setActivationPolicy(.regular)
        NSApp.activate()
        FullScreenToolbar.install()
        if Notifier.isAvailable {
            UNUserNotificationCenter.current().delegate = self
            Notifier.requestAuthorization()
        }
    }

    /// Quitting the app leaves Pal's computer running; it's turned off on purpose.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    /// Clicking a notification opens that bot's chat.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        guard let id = response.notification.request.content.userInfo["palId"] as? String else { return }
        await MainActor.run {
            store?.open(id)
            NSApp.activate()
        }
    }
}
