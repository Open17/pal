import AppKit
import SwiftUI

/// Details panel on the right of a conversation (⌘I).
struct PalInspector: View {
    @Environment(PalStore.self) private var store
    let pal: Pal

    var body: some View {
        let display = store.display(for: pal.id)
        Form {
            Section {
                VStack(spacing: 6) {
                    AvatarView(pal: pal, size: 64, showStatus: true)
                    Text(pal.name).font(.title3.weight(.semibold))
                    Text([pal.role, store.statusLabel(pal)].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
            }

            Section("Model") {
                LabeledContent("Model", value: Models.name(pal.model))
                LabeledContent("Effort", value: Models.effortName(pal.effort))
            }

            Section("Instructions") {
                Text(pal.persona?.isEmpty == false ? pal.persona! : "None")
                    .foregroundStyle(pal.persona?.isEmpty == false ? .primary : .secondary)
                    .textSelection(.enabled)
            }

            Section {
                Button("Edit \(pal.name)…") { store.sheet = .botSettings(pal) }
            }

            Section("Computer") {
                LabeledContent("Screen", value: display.map { DisplayState.label($0.state) } ?? "—")
                LabeledContent("Main folder") {
                    Text("~/workspaces (shared)")
                        .font(.system(size: 11.5, design: .monospaced))
                        .textSelection(.enabled)
                }
            }

            if let error = pal.lastError {
                Section("Last Problem") {
                    Text(error).foregroundStyle(Color.statusRed).textSelection(.enabled)
                }
            }
        }
        .formStyle(.grouped)
    }
}
