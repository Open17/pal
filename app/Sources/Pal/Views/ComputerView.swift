import SwiftUI

/// Every display on Pal's computer: who it belongs to, whether it's awake,
/// and a live look at it.
struct ComputerView: View {
    @Environment(PalStore.self) private var store
    @State private var watching: String?

    var body: some View {
        Group {
            if let watching {
                DisplayView(owner: watching)
                    .toolbar {
                        ToolbarItem(placement: .navigation) {
                            Button("All Displays", systemImage: "chevron.left") { self.watching = nil }
                        }
                    }
            } else {
                grid
            }
        }
        .background(Color.chatBackground)
        .navigationTitle("Computer")
        .navigationSubtitle(store.vm.isRunning ? "On · \(store.displays.filter { $0.state == "running" }.count) awake" : "Off")
    }

    @ViewBuilder
    private var grid: some View {
        if store.displays.isEmpty {
            ContentUnavailableView(
                "No Screens Yet",
                systemImage: "display",
                description: Text(store.vm.isRunning
                    ? "Each bot’s screen shows up here once Pal’s computer has started."
                    : "Turn on Pal’s computer to see your team’s screens.")
            )
        } else {
            cards
        }
    }

    private var cards: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Each bot has its own display. A display starts when its bot needs the computer and falls asleep after 8 idle minutes, keeping its windows open. Watching a display wakes it.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: 14)], spacing: 14) {
                    ForEach(store.displays.sorted { $0.number < $1.number }) { display in
                        DisplayCard(display: display) { watching = display.owner }
                    }
                }
            }
            .padding(24)
        }
    }
}

private struct DisplayCard: View {
    @Environment(PalStore.self) private var store
    let display: Display
    let open: () -> Void

    private var subtitle: String {
        guard let pal = store.pal(display.owner) else { return "Your own desktop" }
        return pal.role.isEmpty ? "Bot" : pal.role
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                if let pal = store.pal(display.owner) {
                    AvatarView(pal: pal, size: 26, showStatus: true)
                } else {
                    AvatarView(name: "You", seed: "operator", size: 26, symbol: "person.fill")
                }
                VStack(alignment: .leading, spacing: 0) {
                    Text(store.displayTitle(display.owner))
                        .font(.system(size: 13, weight: .semibold))
                    Text(subtitle)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
            Button(action: open) {
                ZStack {
                    RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Color.black.opacity(0.85))
                    VStack(spacing: 6) {
                        Image(systemName: display.state == "sleeping" ? "moon.zzz.fill" : display.isLive ? "play.display" : "display")
                            .font(.system(size: 26))
                        Text(display.isLive ? "Watch" : "Start & Watch").font(.caption.weight(.medium))
                    }
                    .foregroundStyle(.white.opacity(0.75))
                }
                .aspectRatio(16 / 10, contentMode: .fit)
            }
            .buttonStyle(.plain)
            HStack(spacing: 6) {
                Circle().fill(DisplayState.color(display.state)).frame(width: 7, height: 7)
                Text(DisplayState.label(display.state)).font(.caption)
                if display.viewers > 0 {
                    Text("· \(display.viewers) watching").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Menu {
                    Button("Wake") { store.wake(display.owner) }
                    Button("Put to Sleep") { store.sleep(display.owner) }.disabled(display.state != "running")
                    Divider()
                    Button("Turn Off (windows reopen next time)") { store.stopDisplay(display.owner) }.disabled(!display.isLive)
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
                .menuStyle(.button)
                .buttonStyle(.plain)
                .menuIndicator(.hidden)
                .fixedSize()
            }
            if let error = display.error {
                Text(error).font(.caption).foregroundStyle(Color.statusRed).lineLimit(2)
            }
        }
        .padding(12)
        .background(GroupBackground())
    }
}
