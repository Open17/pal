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
        HStack(alignment: .bottom, spacing: 6) {
            TextField("Message \(pal.name)", text: draft, axis: .vertical)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .lineLimit(1...10)
                .focused($focused)
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
        .padding(.leading, 6)
        .padding(.trailing, 4)
        .padding(.vertical, 4)
        .glassEffect(.regular, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .onAppear { focused = true }
    }

    private func send() {
        guard canSend else { return }
        store.send(draft.wrappedValue, to: pal.id)
    }
}
