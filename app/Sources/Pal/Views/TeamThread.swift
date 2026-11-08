import SwiftUI

/// A read-only look at a conversation between two bots, opened from a bot's
/// chat. It scrolls to the message that was clicked and highlights it briefly.
struct TeamThreadSheet: View {
    @Environment(PalStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let id: String
    let focus: String?
    @State private var highlighted: String?

    var body: some View {
        let messages = store.teamMessages[id] ?? []
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 14) {
                        ForEach(messages) { message in
                            TeamMessageRow(message: message, highlighted: highlighted == message.id)
                                .id(message.id)
                        }
                    }
                    .frame(maxWidth: 680, alignment: .leading)
                    .frame(maxWidth: .infinity)
                    .padding(24)
                }
                .defaultScrollAnchor(.top, for: .alignment)
                .onAppear {
                    guard let focus else { return }
                    proxy.scrollTo(focus, anchor: .center)
                    highlighted = focus
                    Task {
                        try? await Task.sleep(for: .seconds(1.6))
                        withAnimation(.easeOut(duration: 0.6)) { highlighted = nil }
                    }
                }
            }
            .background(Color.chatBackground)
            .navigationTitle(title)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                        .keyboardShortcut(.defaultAction)
                }
            }
        }
        .frame(minWidth: 560, idealWidth: 640, minHeight: 460, idealHeight: 620)
        .task { await store.loadTeamConversation(id) }
    }

    private var title: String {
        id.components(separatedBy: "--").map(store.name(of:)).joined(separator: " & ")
    }
}

private struct TeamMessageRow: View {
    @Environment(PalStore.self) private var store
    let message: Message
    var highlighted = false

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            if let pal = store.pal(message.sender) {
                AvatarView(pal: pal, size: 28)
            } else {
                AvatarView(name: store.name(of: message.sender), seed: message.sender, size: 28)
            }
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(store.name(of: message.sender)).font(.system(size: 12, weight: .semibold))
                    Image(systemName: "arrow.right").font(.system(size: 9)).foregroundStyle(.tertiary)
                    Text(store.name(of: message.recipient)).font(.system(size: 12)).foregroundStyle(.secondary)
                    Tag(text: kindLabel)
                    Text(Fmt.time(message.createdAt)).font(.system(size: 10.5)).foregroundStyle(.tertiary)
                }
                RichText(text: message.content)
                    .bubble(outgoing: false, first: true, last: true)
            }
        }
        .padding(6)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color.palAccent.opacity(highlighted ? 0.12 : 0))
        )
    }

    private var kindLabel: String {
        switch message.kind {
        case "request": "Asked"
        case "reply": message.metadata["delivered"] == .bool(false) ? "Noted" : "Answered"
        case "notice": "FYI"
        default: message.kind.capitalized
        }
    }
}

/// The rounded, lightly filled background used for grouped content.
struct GroupBackground: View {
    var body: some View {
        RoundedRectangle(cornerRadius: 12, style: .continuous)
            .fill(Color.primary.opacity(0.035))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Color.hairline.opacity(0.6)))
    }
}
