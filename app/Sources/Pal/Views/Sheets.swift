import SwiftUI

/// One bot's name, role, instructions, color, model and effort.
struct BotSettingsSheet: View {
    @Environment(PalStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let pal: Pal
    @State private var name: String
    @State private var role: String
    @State private var persona: String
    @State private var model: String
    @State private var effort: String
    @State private var color: String
    @State private var saving = false
    @State private var error: String?

    init(pal: Pal) {
        self.pal = pal
        _name = State(initialValue: pal.name)
        _role = State(initialValue: pal.role)
        _persona = State(initialValue: pal.persona ?? "")
        _model = State(initialValue: pal.model)
        _effort = State(initialValue: pal.effort)
        _color = State(initialValue: BotTint.hex(of: pal))
    }

    private var trimmedName: String { name.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section {
                    HStack(spacing: 14) {
                        AvatarView(botColor: color, seed: pal.id, size: 52)
                        VStack(alignment: .leading, spacing: 8) {
                            TextField("Name", text: $name, prompt: Text("Required"))
                            TextField("Role", text: $role, prompt: Text("Optional, e.g. Researcher"))
                        }
                    }
                    LabeledContent("Color") {
                        BotColorPicker(hex: $color)
                    }
                }
                Section("Instructions") {
                    InstructionsEditor(text: $persona)
                }
                Section {
                    Picker("Model", selection: $model) {
                        ForEach(Models.all, id: \.id) { Text($0.name).tag($0.id) }
                        if !Models.all.contains(where: { $0.id == model }) { Text(model).tag(model) }
                    }
                    Picker("Effort", selection: $effort) {
                        ForEach(store.effortLevels, id: \.self) { Text(Models.effortName($0)).tag($0) }
                    }
                } footer: {
                    Text("Higher effort thinks longer and uses more of your plan. Changes apply from \(pal.name)’s next message; the conversation carries over.")
                        .foregroundStyle(.secondary)
                }
                if let error {
                    Text(error).foregroundStyle(Color.statusRed)
                }
            }
            .formStyle(.grouped)
            HStack {
                Button("Use Team Defaults") {
                    // Model and effort go back to the team's; edits to the rest are kept.
                    save(resetModel: true)
                }
                .help("Model and effort go back to the team’s. Your other changes are saved.")
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Save") { save(resetModel: false) }
                    .keyboardShortcut(.defaultAction)
                    .disabled(trimmedName.isEmpty || saving)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
        }
        .frame(width: 480)
    }

    private func save(resetModel: Bool) {
        let trimmedRole = role.trimmingCharacters(in: .whitespaces)
        let trimmedPersona = persona.trimmingCharacters(in: .whitespacesAndNewlines)
        var edit = BotEdit()
        if !trimmedName.isEmpty, trimmedName != pal.name { edit.name = trimmedName }
        if trimmedRole != pal.role { edit.role = trimmedRole }
        if trimmedPersona != (pal.persona ?? "") { edit.persona = trimmedPersona }
        if color.caseInsensitiveCompare(BotTint.hex(of: pal)) != .orderedSame { edit.color = color }
        if !resetModel {
            if model != pal.model { edit.model = model }
            if effort != pal.effort { edit.effort = effort }
        }
        saving = true
        error = nil
        Task {
            do {
                if edit != BotEdit() { try await store.editBot(pal.id, edit) }
                if resetModel { store.resetBotSettings(pal.id) }
                dismiss()
            } catch {
                self.error = error.localizedDescription
                saving = false
            }
        }
    }
}

/// A bot's instructions, with a hint while empty.
struct InstructionsEditor: View {
    @Binding var text: String

    var body: some View {
        TextEditor(text: $text)
            .font(.body)
            .frame(minHeight: 110)
            .scrollContentBackground(.hidden)
            .overlay(alignment: .topLeading) {
                if text.isEmpty {
                    Text("Optional: what this bot is for, and how it should work.")
                        .foregroundStyle(.tertiary)
                        .padding(.top, 1)
                        .padding(.leading, 5)
                        .allowsHitTesting(false)
                }
            }
    }
}

/// Add something to shared memory or a bot's knowledge.
struct NewMemorySheet: View {
    @Environment(PalStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let scope: String
    @State private var title = ""
    @State private var description = ""
    @State private var content = ""
    @State private var tags = ""
    @State private var error: String?
    @State private var saving = false

    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section {
                    TextField("Title", text: $title, prompt: Text("Required"))
                    TextField("Summary", text: $description, prompt: Text("One line, used to find it later"))
                    TextField("Tags", text: $tags, prompt: Text("Comma separated"))
                } header: {
                    Text(scope == "shared" ? "Shared memory" : "\(store.name(of: scope))’s knowledge")
                }
                Section("Content") {
                    TextEditor(text: $content)
                        .font(.system(size: 13))
                        .frame(minHeight: 140)
                }
            }
            .formStyle(.grouped)
            HStack {
                if let error {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .font(.callout)
                        .foregroundStyle(Color.statusRed)
                }
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Save") { save() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty || saving)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
        }
        .frame(width: 500, height: 480)
    }

    private func save() {
        saving = true
        let input = MemoryInput(
            title: title.trimmingCharacters(in: .whitespaces),
            content: content,
            description: description,
            tags: tags.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        )
        Task {
            do {
                try await store.saveMemory(input, scope: scope)
                dismiss()
            } catch {
                self.error = error.localizedDescription
                saving = false
            }
        }
    }
}

struct SettingsView: View {
    @Environment(PalStore.self) private var store
    @AppStorage("serverURL") private var serverURL = PalClient.defaultURL
    @AppStorage("token") private var token = ""
    @AppStorage("notifications") private var notifications = true

    var body: some View {
        Form {
            Section {
                if let defaults = store.defaults {
                    Picker("Model", selection: Binding(get: { defaults.model }, set: { store.updateDefaults(model: $0) })) {
                        ForEach(Models.all, id: \.id) { Text($0.name).tag($0.id) }
                    }
                    Picker("Effort", selection: Binding(get: { defaults.effort }, set: { store.updateDefaults(effort: $0) })) {
                        ForEach(store.effortLevels, id: \.self) { Text(Models.effortName($0)).tag($0) }
                    }
                } else {
                    Text("Available when Pal’s computer is on.").foregroundStyle(.secondary)
                }
            } header: {
                Text("Team Defaults")
            } footer: {
                Text("Every bot uses these unless you’ve chosen something else for it.").foregroundStyle(.secondary)
            }

            Section {
                TextField("Address", text: $serverURL)
                    .font(.system(.body, design: .monospaced))
                SecureField("Token", text: $token, prompt: Text("Read from the VM automatically"))
                LabeledContent("Status") {
                    HStack(spacing: 6) {
                        Circle()
                            .fill(store.connection == .online ? Color.statusGreen : .secondary)
                            .frame(width: 8, height: 8)
                        Text(statusText).lineLimit(1)
                        Button("Reconnect") { store.reconnect() }
                    }
                }
            } header: {
                Text("Connection")
            } footer: {
                Text("Pal’s computer makes its API available only on this Mac. Leave these as they are unless you know you need to change them.")
                    .foregroundStyle(.secondary)
            }

            Section {
                Toggle("Notify me about replies", isOn: $notifications)
                    .disabled(!Notifier.isAvailable)
            } header: {
                Text("Notifications")
            } footer: {
                if !Notifier.isAvailable {
                    Text("Available when Pal runs as an app (app/scripts/pal.sh bundle).").foregroundStyle(.secondary)
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 480)
        .fixedSize(horizontal: false, vertical: true)
    }

    private var statusText: String {
        switch store.connection {
        case .online: "Connected to \(store.client.displayAddress)"
        case .connecting: "Connecting…"
        case .offline(let why): why
        }
    }
}

/// Add a bot to the team: a name, and optionally what it's for.
struct NewBotSheet: View {
    @Environment(PalStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var role = ""
    @State private var persona = ""
    @State private var color: String?
    @State private var saving = false
    @State private var error: String?

    private var canCreate: Bool { !name.trimmingCharacters(in: .whitespaces).isEmpty && !saving }

    /// The chosen color, or the first one nobody on the team is using.
    private var chosenColor: String { color ?? BotColors.firstUnused(by: store.pals.map(\.color)).hex }

    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section {
                    HStack(spacing: 14) {
                        AvatarView(botColor: chosenColor, seed: name, size: 52)
                        VStack(alignment: .leading, spacing: 8) {
                            TextField("Name", text: $name, prompt: Text("Research Pal"))
                            TextField("Role", text: $role, prompt: Text("Optional, e.g. Researcher"))
                        }
                    }
                    LabeledContent("Color") {
                        BotColorPicker(hex: Binding(get: { chosenColor }, set: { color = $0 }))
                    }
                } footer: {
                    Text("Each bot has its own display and browser, and shares the computer, files and logins with the rest of the team.")
                        .foregroundStyle(.secondary)
                }
                Section("Instructions") {
                    InstructionsEditor(text: $persona)
                }
                if let error {
                    Text(error).foregroundStyle(Color.statusRed)
                }
            }
            .formStyle(.grouped)
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Add to Team") { create() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(!canCreate)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
        }
        .frame(width: 460)
    }

    private func create() {
        saving = true
        error = nil
        Task {
            do {
                try await store.createBot(
                    name: name.trimmingCharacters(in: .whitespaces),
                    role: role.trimmingCharacters(in: .whitespaces),
                    persona: persona.trimmingCharacters(in: .whitespacesAndNewlines),
                    color: chosenColor
                )
                dismiss()
            } catch {
                self.error = error.localizedDescription
                saving = false
            }
        }
    }
}
