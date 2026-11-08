import SwiftUI

/// Shared team memory and each bot's private knowledge.
struct MemoryView: View {
    @Environment(PalStore.self) private var store
    @State private var scope = "shared"
    @State private var selected: MemoryEntry.ID?
    @State private var query = ""
    @State private var pendingDelete: MemoryEntry?

    private var entries: [MemoryEntry] {
        let all = scope == "shared" ? store.sharedMemory : store.botMemory[scope] ?? []
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return all }
        return all.filter {
            $0.title.localizedCaseInsensitiveContains(q) || $0.description.localizedCaseInsensitiveContains(q)
                || $0.body.localizedCaseInsensitiveContains(q)
                || $0.tags.contains { $0.localizedCaseInsensitiveContains(q) }
        }
    }

    private var selectedEntry: MemoryEntry? {
        entries.first { $0.id == selected }
    }

    var body: some View {
        HSplitView {
            VStack(spacing: 0) {
                Picker("Whose", selection: $scope) {
                    Text("Shared").tag("shared")
                    ForEach(store.pals) { pal in Text(pal.name).tag(pal.id) }
                }
                .pickerStyle(.menu)
                .labelsHidden()
                .padding(10)
                List(selection: $selected) {
                    if entries.isEmpty {
                        Text(scope == "shared" ? "Nothing in shared memory yet." : "\(store.name(of: scope)) hasn’t saved anything yet.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(entries) { entry in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(entry.title).font(.system(size: 13, weight: .medium))
                            Text(entry.description.isEmpty ? entry.body.previewLine : entry.description)
                                .font(.system(size: 11.5))
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                        }
                        .padding(.vertical, 3)
                        .tag(entry.id)
                        .contextMenu {
                            Button("Edit…") { store.sheet = .editMemory(scope: scope, entry: entry) }
                            Divider()
                            Button("Delete…", role: .destructive) { pendingDelete = entry }
                        }
                    }
                }
                .listStyle(.inset)
                .onDeleteCommand { pendingDelete = selectedEntry }
            }
            .frame(minWidth: 260, idealWidth: 300, maxWidth: 400)

            Group {
                if let entry = selectedEntry {
                    MemoryDetail(entry: entry)
                } else {
                    ContentUnavailableView("Long-Term Memory", systemImage: "brain", description: Text("What your team remembers between conversations. Shared memory is visible to every bot."))
                }
            }
            .frame(minWidth: 380, maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.chatBackground)
        }
        .searchable(text: $query, prompt: "Search memory")
        .navigationTitle("Memory")
        .navigationSubtitle("\(entries.count) \(entries.count == 1 ? "entry" : "entries")")
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button("Edit", systemImage: "pencil") {
                    selectedEntry.map { store.sheet = .editMemory(scope: scope, entry: $0) }
                }
                .help("Change this memory")
                .disabled(selectedEntry == nil)
                Button("Delete", systemImage: "trash") { pendingDelete = selectedEntry }
                    .help("Delete this memory (⌫)")
                    .disabled(selectedEntry == nil)
                Button("Add Memory", systemImage: "plus") { store.sheet = .newMemory(scope: scope) }
                    .help("Add something for the team to remember")
            }
        }
        .task { await store.loadMemory() }
        // Opened from search: show that entry, in its own list.
        .onChange(of: store.focusedMemory, initial: true) { _, focus in
            guard let focus else { return }
            store.focusedMemory = nil
            query = ""
            scope = focus.scope
            selected = focus.id
        }
        .confirmationDialog("Delete “\(pendingDelete?.title ?? "")”?", isPresented: Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } })) {
            Button("Delete", role: .destructive) {
                if let entry = pendingDelete { store.deleteMemory(entry, scope: scope) }
                pendingDelete = nil
            }
        }
    }
}

private struct MemoryDetail: View {
    @Environment(PalStore.self) private var store
    let entry: MemoryEntry

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(entry.title).font(.title2.weight(.semibold)).textSelection(.enabled)
                if !entry.description.isEmpty {
                    Text(entry.description).foregroundStyle(.secondary)
                }
                HStack(spacing: 6) {
                    Tag(text: entry.kind)
                    ForEach(entry.tags, id: \.self) { Tag(text: "#\($0)") }
                    Spacer()
                    Text("By \(store.name(of: entry.author)) · updated \(Fmt.relativeInline(entry.updatedAt))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Divider()
                RichText(text: entry.body.isEmpty ? "(empty)" : entry.body)
            }
            .padding(24)
            .frame(maxWidth: 720, alignment: .leading)
        }
    }
}
