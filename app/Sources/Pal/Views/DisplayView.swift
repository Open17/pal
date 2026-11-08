import AppKit
import SwiftUI

/// A live view of a bot's (or the operator's) display, with optional control.
///
/// Connecting wakes the display and keeps it awake while you watch. Control is
/// off by default so watching never disturbs a bot mid-task.
struct DisplayView: View {
    @Environment(PalStore.self) private var store
    @Environment(\.openWindow) private var openWindow
    let owner: String
    var showsHeader = true

    @State private var frame: CGImage?
    @State private var state: RemoteDisplay.State = .connecting
    @State private var controlling = false
    @State private var connection: RemoteDisplay?
    @State private var attempt = 0

    private var display: Display? { store.display(for: owner) }

    var body: some View {
        VStack(spacing: 0) {
            if showsHeader { header }
            ZStack {
                Color.black
                if let frame {
                    DisplayCanvas(image: frame, controlling: controlling, connection: connection)
                        .frame(minWidth: 0, maxWidth: .infinity, minHeight: 0, maxHeight: .infinity)
                }
                overlay
            }
            // Match the display's shape so there are no black bars around it.
            .aspectRatio(frame.map { CGFloat($0.width) / CGFloat(max($0.height, 1)) } ?? 16 / 10, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: showsHeader ? 10 : 0, style: .continuous))
            .padding(showsHeader ? 10 : 0)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .task(id: "\(owner)-\(attempt)") { await connect() }
        .onDisappear { connection?.stop() }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Circle().fill(stateColor).frame(width: 7, height: 7)
            Text(display.map { "\(store.displayTitle(owner)) · \($0.display)" } ?? store.displayTitle(owner))
                .font(.system(size: 12, weight: .semibold))
            Text(stateText)
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
            Spacer()
            Toggle(isOn: $controlling) {
                Label(controlling ? "In Control" : "Take Control", systemImage: controlling ? "cursorarrow.rays" : "cursorarrow")
            }
            .toggleStyle(.button)
            .controlSize(.small)
            .help(controlling ? "Your mouse and keyboard go to this display" : "Watch only")
            Menu {
                Button("Open in Window") { openWindow(id: "display", value: owner) }
                Button("Reconnect") { attempt += 1 }
                Divider()
                Button("Put Display to Sleep") { store.sleep(owner) }
                Button("Turn Off Display") { store.stopDisplay(owner) }
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.button)
            .buttonStyle(.plain)
            .menuIndicator(.hidden)
            .fixedSize()
        }
        .padding(.horizontal, 14)
        .padding(.top, 10)
    }

    @ViewBuilder
    private var overlay: some View {
        switch state {
        case .connecting where frame == nil:
            VStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text(display?.isLive == true ? "Connecting…" : "Starting \(store.displayTitle(owner))…")
                    .font(.callout)
                    .foregroundStyle(.white.opacity(0.7))
            }
        case .failed(let reason):
            VStack(spacing: 10) {
                Image(systemName: "display.trianglebadge.exclamationmark")
                    .font(.largeTitle)
                    .foregroundStyle(.white.opacity(0.6))
                Text(reason)
                    .font(.callout)
                    .foregroundStyle(.white.opacity(0.75))
                    .multilineTextAlignment(.center)
                Button("Try Again") { attempt += 1 }
            }
            .padding(24)
        default:
            EmptyView()
        }
    }

    private var stateText: String {
        switch state {
        case .connecting: "Connecting"
        case .connected: controlling ? "You have control" : "Watching"
        case .failed: "Not connected"
        case .closed: "Closed"
        }
    }

    private var stateColor: Color {
        switch state {
        case .connected: controlling ? .statusOrange : .statusGreen
        case .failed: .statusRed
        default: .secondary
        }
    }

    private func connect() async {
        connection?.stop()
        frame = nil
        guard let display else {
            state = .failed("This display isn't available yet.")
            return
        }
        guard let password = Secrets.vncPassword else {
            state = .failed("No VNC password found in the VM's secrets folder.")
            return
        }
        let remote = RemoteDisplay(port: store.vncPort(for: display), password: password)
        remote.onState = { state = $0 }
        remote.onFrame = { frame = $0 }
        connection = remote
        remote.start()
    }
}

/// Draws frames and turns mouse and keyboard input into VNC events.
private struct DisplayCanvas: NSViewRepresentable {
    let image: CGImage
    let controlling: Bool
    let connection: RemoteDisplay?

    func makeNSView(context: Context) -> CanvasView {
        CanvasView()
    }

    func updateNSView(_ view: CanvasView, context: Context) {
        view.connection = connection
        view.controlling = controlling
        view.show(image)
    }
}

private final class CanvasView: NSView {
    var connection: RemoteDisplay?
    var controlling = false {
        didSet {
            if controlling, oldValue != controlling { window?.makeFirstResponder(self) }
            window?.invalidateCursorRects(for: self)
        }
    }
    private var imageSize = CGSize.zero
    private var buttons: UInt8 = 0
    private var modifiers: NSEvent.ModifierFlags = []

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.contentsGravity = .resizeAspect
        layer?.magnificationFilter = .linear
    }

    required init?(coder: NSCoder) { fatalError() }

    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { controlling }

    func show(_ image: CGImage) {
        imageSize = CGSize(width: image.width, height: image.height)
        layer?.contents = image
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: bounds, options: [.mouseMoved, .activeInKeyWindow, .inVisibleRect], owner: self))
    }

    /// The display coordinates under a point in this view (aspect-fit).
    private func location(_ event: NSEvent) -> (Int, Int)? {
        guard imageSize.width > 0, imageSize.height > 0 else { return nil }
        let point = convert(event.locationInWindow, from: nil)
        let scale = min(bounds.width / imageSize.width, bounds.height / imageSize.height)
        let origin = CGPoint(x: (bounds.width - imageSize.width * scale) / 2, y: (bounds.height - imageSize.height * scale) / 2)
        return (Int((point.x - origin.x) / scale), Int((point.y - origin.y) / scale))
    }

    private func sendPointer(_ event: NSEvent) {
        guard controlling, let connection, let (x, y) = location(event) else { return }
        connection.pointer(x: x, y: y, buttons: buttons)
    }

    override func mouseDown(with event: NSEvent) { press(1, event) }
    override func mouseUp(with event: NSEvent) { release(1, event) }
    override func rightMouseDown(with event: NSEvent) { press(4, event) }
    override func rightMouseUp(with event: NSEvent) { release(4, event) }
    override func otherMouseDown(with event: NSEvent) { press(2, event) }
    override func otherMouseUp(with event: NSEvent) { release(2, event) }
    override func mouseMoved(with event: NSEvent) { sendPointer(event) }
    override func mouseDragged(with event: NSEvent) { sendPointer(event) }
    override func rightMouseDragged(with event: NSEvent) { sendPointer(event) }

    private func press(_ button: UInt8, _ event: NSEvent) {
        if controlling { window?.makeFirstResponder(self) }
        buttons |= button
        sendPointer(event)
    }

    private func release(_ button: UInt8, _ event: NSEvent) {
        buttons &= ~button
        sendPointer(event)
    }

    override func scrollWheel(with event: NSEvent) {
        guard controlling, let connection, let (x, y) = location(event), event.scrollingDeltaY != 0 else { return }
        connection.scroll(x: x, y: y, up: event.scrollingDeltaY > 0)
    }

    override func keyDown(with event: NSEvent) {
        guard controlling, let keysym = KeySym.from(event) else { return }
        connection?.key(keysym, down: true)
    }

    override func keyUp(with event: NSEvent) {
        guard controlling, let keysym = KeySym.from(event) else { return }
        connection?.key(keysym, down: false)
    }

    override func flagsChanged(with event: NSEvent) {
        guard controlling else { return }
        let flags = event.modifierFlags.intersection([.shift, .control, .option, .command])
        for (flag, keysym) in [(NSEvent.ModifierFlags.shift, KeySym.shift), (.control, KeySym.control), (.option, KeySym.option), (.command, KeySym.command)]
        where flags.contains(flag) != modifiers.contains(flag) {
            connection?.key(keysym, down: flags.contains(flag))
        }
        modifiers = flags
    }

    /// Let ⌘-shortcuts reach the VM while in control, instead of the app's menus.
    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        guard controlling, window?.firstResponder === self else { return super.performKeyEquivalent(with: event) }
        keyDown(with: event)
        keyUp(with: event)
        return true
    }

    /// While in control, only the VM's own cursor shows: the server draws it
    /// into the picture, so the Mac's would be a second one on top.
    private static let hidden = NSCursor(image: NSImage(size: NSSize(width: 1, height: 1)), hotSpot: .zero)

    override func resetCursorRects() {
        if controlling { addCursorRect(bounds, cursor: Self.hidden) }
    }
}

/// A display in its own window (Pal ▸ Window, or "Open in Window").
struct DisplayWindow: View {
    @Environment(PalStore.self) private var store
    let owner: String

    var body: some View {
        DisplayView(owner: owner)
            .frame(minWidth: 640, minHeight: 400)
            .navigationTitle(store.displayTitle(owner))
            .background(Color.chatBackground)
    }
}
