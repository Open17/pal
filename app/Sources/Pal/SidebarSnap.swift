import AppKit

/// Makes the sidebar hide and show instantly instead of sliding.
///
/// SwiftUI animates column changes; collapsing the underlying split view item
/// directly skips that, and SwiftUI then finds the sidebar already where it
/// wants it.
enum SidebarSnap {
    static func setCollapsed(_ collapsed: Bool) {
        guard let sidebar = sidebarItem(), sidebar.isCollapsed != collapsed else { return }
        sidebar.isCollapsed = collapsed
    }

    /// Keeps the sidebar between `min` and `max` wide while it's shown.
    ///
    /// SwiftUI ignores `navigationSplitViewColumnWidth` here, so the sidebar
    /// could be dragged wide enough to push the chat and details out of the
    /// window, leaving it blank, or narrow enough to cut off its rows. The
    /// split view does respect Auto Layout constraints on its panes, so this
    /// limits the sidebar pane directly.
    ///
    /// The minimum sits just below required, so hiding the sidebar (which
    /// takes it to zero width) still wins over it.
    static func limitWidth(min: CGFloat, max: CGFloat) {
        for window in NSApp.windows {
            guard let split = sidebarSplitView(in: window.contentView),
                  let sidebar = split.arrangedSubviews.first,
                  !sidebar.constraints.contains(where: { $0.identifier == maxWidthID })
            else { continue }
            let cap = sidebar.widthAnchor.constraint(lessThanOrEqualToConstant: max)
            cap.identifier = maxWidthID
            let floor = sidebar.widthAnchor.constraint(greaterThanOrEqualToConstant: min)
            floor.identifier = minWidthID
            floor.priority = .defaultHigh
            NSLayoutConstraint.activate([cap, floor])
        }
    }

    private static let maxWidthID = "pal.sidebar.maxWidth"
    private static let minWidthID = "pal.sidebar.minWidth"

    /// The split view behind `NavigationSplitView`: the outermost side-by-side one.
    private static func sidebarSplitView(in view: NSView?) -> NSSplitView? {
        guard let view else { return nil }
        if let split = view as? NSSplitView, split.isVertical, split.arrangedSubviews.count >= 2 { return split }
        return view.subviews.lazy.compactMap(sidebarSplitView).first
    }

    private static func sidebarItem() -> NSSplitViewItem? {
        func find(_ vc: NSViewController?) -> NSSplitViewItem? {
            guard let vc else { return nil }
            if let split = vc as? NSSplitViewController, let item = split.splitViewItems.first(where: { $0.behavior == .sidebar }) {
                return item
            }
            return vc.children.lazy.compactMap(find).first
        }
        return NSApp.windows.lazy.compactMap { find($0.contentViewController) }.first
    }
}
