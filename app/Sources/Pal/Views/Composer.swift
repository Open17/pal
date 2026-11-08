import AppKit
import SwiftUI

struct Composer: View {
    @Environment(PalStore.self) private var store
    let pal: Pal
    @FocusState private var focused: Bool

    private var draft: Binding<String> {
        Binding(get: { store.drafts[pal.id] ?? "" }, set: { store.drafts[pal.id] = $0 })
    }

    private var canSend: Bool {
        !draft.wrappedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var busy: Bool { pal.status.isWorking }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let quoted = store.replyingTo[pal.id] {
                ReplyBanner(name: store.name(of: quoted.sender), text: quoted.content) {
                    store.replyingTo[pal.id] = nil
                }
                .transition(.opacity.combined(with: .move(edge: .bottom)))
            }
            field
        }
        .padding(.leading, 6)
        .padding(.trailing, 4)
        .padding(.vertical, 4)
        .glassEffect(.regular, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .animation(.snappy(duration: 0.2), value: store.replyingTo[pal.id]?.id)
        .onAppear { focused = true }
        // Replying puts you in the message field.
        .onChange(of: store.replyingTo[pal.id]?.id) { _, id in if id != nil { focused = true } }
    }

    private var field: some View {
        HStack(alignment: .bottom, spacing: 6) {
            TextField("Message \(pal.name)", text: draft, axis: .vertical)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .lineLimit(1...10)
                .focused($focused)
                .onKeyPress(.escape) {
                    guard store.replyingTo[pal.id] != nil else { return .ignored }
                    store.replyingTo[pal.id] = nil
                    return .handled
                }
                .onKeyPress(.return, phases: .down) { press in
                    // Return sends; Shift- or Option-Return starts a new line.
                    if press.modifiers.contains(.shift) || press.modifiers.contains(.option) {
                        draft.wrappedValue += "\n"
                    } else {
                        send()
                    }
                    return .handled
                }
                .padding(.vertical, 5)
                .padding(.leading, 10)

            Button {
                if canSend { send() } else if busy { store.interrupt(pal.id) }
            } label: {
                Image(systemName: !canSend && busy ? "stop.circle.fill" : "arrow.up.circle.fill")
                    .font(.system(size: 24))
                    .symbolRenderingMode(.palette)
                    .foregroundStyle(.white, canSend || busy ? Color.palAccent : Color.secondary.opacity(0.35))
                    .contentTransition(.symbolEffect(.replace))
            }
            .buttonStyle(.plain)
            .disabled(!canSend && !busy)
            .help(!canSend && busy ? "Stop (⌘.)" : "Send (Return)")
        }
    }

    private func send() {
        guard canSend else { return }
        store.send(draft.wrappedValue, to: pal.id)
    }
}

/// The message you're replying to, above the message field.
private struct ReplyBanner: View {
    let name: String
    let text: String
    let cancel: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "arrowshape.turn.up.left.fill")
                .font(.system(size: 10))
                .foregroundStyle(Color.palAccent)
            VStack(alignment: .leading, spacing: 1) {
                Text("Replying to \(name)")
                    .font(.system(size: 11, weight: .semibold))
                Text(text.previewLine)
                    .font(.system(size: 11.5))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            Button("Cancel Reply", systemImage: "xmark.circle.fill", action: cancel)
                .labelStyle(.iconOnly)
                .buttonStyle(.plain)
                .foregroundStyle(.tertiary)
                .help("Cancel the reply (Esc)")
        }
        .padding(.horizontal, 10)
        .padding(.top, 6)
        .padding(.bottom, 2)
    }
}
