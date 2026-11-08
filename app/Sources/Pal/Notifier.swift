import AppKit
import UserNotifications

/// System notifications for replies and approval requests while Pal is in the background.
/// Only available when running as Pal.app; macOS doesn't allow them for a bare executable.
enum Notifier {
    static var isAvailable: Bool {
        Bundle.main.bundleURL.pathExtension == "app"
    }

    static var enabled: Bool {
        UserDefaults.standard.object(forKey: "notifications") as? Bool ?? true
    }

    static func requestAuthorization() {
        guard isAvailable else { return }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    static func post(id: String, title: String, body: String, palId: String) {
        guard isAvailable, enabled else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        content.threadIdentifier = palId
        content.userInfo = ["palId": palId]
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: id, content: content, trigger: nil))
    }
}
