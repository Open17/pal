import AppKit
import ObjectiveC

/// Removes the solid bar behind the toolbar in full screen, and keeps the
/// window buttons showing there.
///
/// In full screen AppKit moves the toolbar into its own window and paints a
/// title-bar background there, so the conversation stops under a flat bar
/// instead of scrolling beneath the toolbar as it does in a normal window.
/// SwiftUI's toolbar-background and scroll-edge settings don't reach that
/// window.
///
/// Hiding the background after the fact flashes it (entering full screen,
/// switching bots rebuilds the toolbar), so instead this teaches AppKit's
/// background view class to stay hidden whenever it's in the full-screen
/// toolbar window: it hides itself as it arrives there, and refuses to be
/// shown again while it stays. Back in a normal window it behaves as usual.
/// The conversation's own top fade (see `ConversationView`) keeps text under
/// the toolbar readable.
///
/// Relies on AppKit's private class names; if they change, nothing is patched:
/// the solid bar comes back and the buttons hide again until the menu bar shows.
enum FullScreenToolbar {
    private static let backgroundClass = "NSTitlebarBackgroundView"
    private static let fullScreenToolbarWindowClass = "NSToolbarFullScreenWindow"
    private static let windowButtonClass = "_NSThemeWidget"
    nonisolated(unsafe) private static var hiddenByUs = 0

    @MainActor
    static func install() {
        if let background = NSClassFromString(backgroundClass) {
            patchSetHidden(background)
            patchDidMoveToWindow(background)
        }
        if let buttons = NSClassFromString(windowButtonClass) {
            patchButtonAlpha(buttons)
            patchButtonMove(buttons)
        }
    }

    private static func inFullScreenToolbar(_ view: NSView) -> Bool {
        guard let window = view.window else { return false }
        return String(describing: type(of: window)) == fullScreenToolbarWindowClass
    }

    /// `isHidden = false` is ignored while the view is in the full-screen toolbar.
    private static func patchSetHidden(_ cls: AnyClass) {
        let sel = #selector(setter: NSView.isHidden)
        guard let method = class_getInstanceMethod(cls, sel) else { return }
        typealias Fn = @convention(c) (NSView, Selector, Bool) -> Void
        let original = unsafeBitCast(method_getImplementation(method), to: Fn.self)
        let block: @convention(block) (NSView, Bool) -> Void = { view, hidden in
            MainActor.assumeIsolated {
                original(view, sel, hidden || inFullScreenToolbar(view))
            }
        }
        replace(cls, sel, with: imp_implementationWithBlock(block), types: method_getTypeEncoding(method))
    }

    /// Hides the view as it enters the full-screen toolbar, before it ever
    /// draws, and shows it again if it goes back to a normal window.
    private static func patchDidMoveToWindow(_ cls: AnyClass) {
        let sel = #selector(NSView.viewDidMoveToWindow)
        guard let method = class_getInstanceMethod(cls, sel) else { return }
        typealias Fn = @convention(c) (NSView, Selector) -> Void
        let original = unsafeBitCast(method_getImplementation(method), to: Fn.self)
        let block: @convention(block) (NSView) -> Void = { view in
            MainActor.assumeIsolated { didMove(view, original: original, sel: sel) }
        }
        replace(cls, sel, with: imp_implementationWithBlock(block), types: method_getTypeEncoding(method))
    }

    private static func didMove(_ view: NSView, original: @convention(c) (NSView, Selector) -> Void, sel: Selector) {
        original(view, sel)
        let key = UnsafeRawPointer(&hiddenByUs)
        if inFullScreenToolbar(view) {
            if !view.isHidden {
                objc_setAssociatedObject(view, key, true, .OBJC_ASSOCIATION_RETAIN_NONATOMIC)
                view.isHidden = true
            }
        } else if objc_getAssociatedObject(view, key) as? Bool == true {
            objc_setAssociatedObject(view, key, nil, .OBJC_ASSOCIATION_RETAIN_NONATOMIC)
            view.isHidden = false
        }
    }

    /// Keeps the close, minimize and zoom buttons showing in full screen.
    ///
    /// AppKit fades them to transparent just before moving them into the
    /// full-screen toolbar, and only brings them back while the menu bar is
    /// revealed. They stay in place and clickable either way. So: make them
    /// opaque as they arrive there, and ignore any fade while they stay.
    private static func patchButtonMove(_ cls: AnyClass) {
        let sel = #selector(NSView.viewDidMoveToWindow)
        guard let method = class_getInstanceMethod(cls, sel) else { return }
        typealias Fn = @convention(c) (NSView, Selector) -> Void
        let original = unsafeBitCast(method_getImplementation(method), to: Fn.self)
        let block: @convention(block) (NSView) -> Void = { view in
            MainActor.assumeIsolated {
                original(view, sel)
                if inFullScreenToolbar(view) { view.alphaValue = 1 }
            }
        }
        replace(cls, sel, with: imp_implementationWithBlock(block), types: method_getTypeEncoding(method))
    }

    private static func patchButtonAlpha(_ cls: AnyClass) {
        let sel = #selector(setter: NSView.alphaValue)
        guard let method = class_getInstanceMethod(cls, sel) else { return }
        typealias Fn = @convention(c) (NSView, Selector, CGFloat) -> Void
        let original = unsafeBitCast(method_getImplementation(method), to: Fn.self)
        let block: @convention(block) (NSView, CGFloat) -> Void = { view, alpha in
            MainActor.assumeIsolated {
                original(view, sel, inFullScreenToolbar(view) ? 1 : alpha)
            }
        }
        replace(cls, sel, with: imp_implementationWithBlock(block), types: method_getTypeEncoding(method))
    }

    /// Overrides the method on this class only: adds it when the class just
    /// inherits it (so NSView itself is untouched), or swaps it when the class
    /// defines its own.
    private static func replace(_ cls: AnyClass, _ sel: Selector, with imp: IMP, types: UnsafePointer<CChar>?) {
        if !class_addMethod(cls, sel, imp, types), let own = class_getInstanceMethod(cls, sel) {
            method_setImplementation(own, imp)
        }
    }
}

/// How far the full-screen toolbar has slid down to make room for the menu bar.
///
/// In full screen the toolbar lives in its own window, which AppKit moves down
/// when the menu bar is revealed. Views in the toolbar go with it; views in the
/// conversation (the name pill under the avatar) don't, so they read this and
/// move by the same amount.
@Observable
final class ToolbarDrop {
    static let shared = ToolbarDrop()
    private(set) var amount: CGFloat = 0

    private init() {
        for name in [NSWindow.didMoveNotification, NSWindow.didResizeNotification, NSWindow.didEnterFullScreenNotification, NSWindow.didExitFullScreenNotification] {
            NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { _ in
                MainActor.assumeIsolated { ToolbarDrop.shared.update() }
            }
        }
    }

    private func update() {
        let toolbar = NSApp.windows.first { String(describing: type(of: $0)) == "NSToolbarFullScreenWindow" && $0.isVisible }
        let main = NSApp.windows.first { $0.styleMask.contains(.fullScreen) }
        var drop: CGFloat = 0
        if let toolbar, let main, toolbar.screen == main.screen {
            drop = max(0, main.frame.maxY - toolbar.frame.maxY)
        }
        if drop != amount { amount = drop }
    }
}
