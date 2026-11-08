import AppKit
import SwiftUI

/// Pal's bot glyph: a rounded head with an antenna, side ears and cut-out eyes.
/// The eyes are holes, so whatever sits behind the mark shows through them.
struct BotMark: Shape {
    /// 1 is wide open, 0 is shut (a thin slit). Animatable, for blinking.
    var eyesOpen: CGFloat = 1

    var animatableData: CGFloat {
        get { eyesOpen }
        set { eyesOpen = newValue }
    }

    func path(in rect: CGRect) -> Path {
        // Drawn on a unit square, then scaled to fit `rect` without stretching.
        let side = min(rect.width, rect.height)
        let origin = CGPoint(x: rect.midX - side / 2, y: rect.midY - side / 2)
        func r(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) -> CGRect {
            CGRect(x: origin.x + x * side, y: origin.y + y * side, width: w * side, height: h * side)
        }

        let head = Path(roundedRect: r(0.14, 0.33, 0.72, 0.56), cornerRadius: 0.2 * side, style: .continuous)
        let stem = Path(roundedRect: r(0.465, 0.18, 0.07, 0.18), cornerRadius: 0.035 * side)
        let bulb = Path(ellipseIn: r(0.42, 0.06, 0.16, 0.16))
        let leftEar = Path(roundedRect: r(0.06, 0.52, 0.12, 0.2), cornerRadius: 0.05 * side)
        let rightEar = Path(roundedRect: r(0.82, 0.52, 0.12, 0.2), cornerRadius: 0.05 * side)

        // Eyes close toward their middle, like a blink.
        let open = min(max(eyesOpen, 0), 1)
        let eyeHeight = 0.035 + (0.19 - 0.035) * open
        let eyeTop = 0.595 - eyeHeight / 2
        let eyeRadius = min(0.055, eyeHeight / 2) * side
        let leftEye = Path(roundedRect: r(0.315, eyeTop, 0.11, eyeHeight), cornerRadius: eyeRadius)
        let rightEye = Path(roundedRect: r(0.575, eyeTop, 0.11, eyeHeight), cornerRadius: eyeRadius)

        return head
            .union(stem).union(bulb).union(leftEar).union(rightEar)
            .subtracting(leftEye.union(rightEye))
    }
}

/// The bot mark, blinking now and then. Each one keeps its own rhythm, so a
/// team of avatars doesn't blink in unison. Holds still with Reduce Motion on.
struct BlinkingBotMark: View {
    var ink: Color
    @State private var eyesOpen: CGFloat = 1
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        BotMark(eyesOpen: eyesOpen)
            .fill(ink)
            .task(id: reduceMotion) {
                eyesOpen = 1
                guard !reduceMotion else { return }
                do {
                    // Start at a random point so avatars that appear together don't sync up.
                    try await Task.sleep(for: .seconds(Double.random(in: 0.5...5)))
                    while true {
                        try await blink()
                        if Double.random(in: 0...1) < 0.2 { try await blink() } // now and then, twice
                        try await Task.sleep(for: .seconds(Double.random(in: 2.5...6.5)))
                    }
                } catch {
                    eyesOpen = 1 // cancelled: the view went away
                }
            }
    }

    private func blink() async throws {
        withAnimation(.easeIn(duration: 0.07)) { eyesOpen = 0 }
        try await Task.sleep(for: .milliseconds(110))
        withAnimation(.easeOut(duration: 0.12)) { eyesOpen = 1 }
        try await Task.sleep(for: .milliseconds(160))
    }
}

/// The colors an avatar is drawn in, worked out from one base color.
struct BotTint: Hashable {
    /// The background: the bot's color, flat.
    let fill: Color
    /// The glyph: white on darker colors, a deep shade of the base on light ones.
    let ink: Color
    /// Near-white fills get a faint edge so they don't vanish on light backgrounds.
    let needsOutline: Bool

    private init(fill: Color, ink: Color) {
        self.fill = fill
        self.ink = ink
        needsOutline = false
    }

    /// Black with a white bot in light mode, white with a black bot in dark mode.
    static let mono = BotTint(fill: .adaptive(0x000000, 0xFFFFFF), ink: .adaptive(0xFFFFFF, 0x000000))

    init(_ base: NSColor) {
        let c = base.usingColorSpace(.sRGB) ?? base
        let (h, s, b) = (c.hueComponent, c.saturationComponent, c.brightnessComponent)
        fill = Color(nsColor: c)
        let luminance = 0.2126 * c.redComponent + 0.7152 * c.greenComponent + 0.0722 * c.blueComponent
        needsOutline = luminance > 0.9
        // Grays have no real hue; don't tint their ink with one.
        let inkSaturation = s < 0.08 ? 0 : min(1, s * 1.1 + 0.15)
        ink = luminance > 0.62 ? Color(hue: h, saturation: inkSaturation, brightness: b * 0.38) : .white
    }

    /// A bot's tint: its configured color, or one picked from its id when it has none
    /// (or the color can't be read).
    static func of(color: String?, seed: String) -> BotTint {
        let value = hex(color: color, seed: seed)
        if BotColors.isMono(value) { return .mono }
        return BotTint(NSColor(hexString: value)!)
    }

    /// The color value a bot is drawn in (a hex, or "mono"), configured or picked.
    static func hex(color: String?, seed: String) -> String {
        if let color, BotColors.isMono(color) || NSColor(hexString: color) != nil { return color }
        return BotColors.forSeed(seed).hex
    }

    static func hex(of pal: Pal) -> String { hex(color: pal.color, seed: pal.id) }
}

/// Colors offered when adding a bot.
enum BotColors {
    struct Swatch: Identifiable, Hashable {
        let name: String
        /// "#RRGGBB", or "mono".
        let hex: String
        var id: String { hex }
    }

    /// Black in light mode, white in dark mode. Stored as this word instead of a hex.
    static let mono = Swatch(name: "Black & White", hex: "mono")

    static func isMono(_ value: String) -> Bool { value.caseInsensitiveCompare(mono.hex) == .orderedSame }

    /// Every swatch the picker offers.
    static let all: [Swatch] = hues + [mono]

    /// The colored swatches, also used to pick a color for a bot that has none.
    static let hues: [Swatch] = [
        .init(name: "Blue", hex: "#5B8DEF"),
        .init(name: "Indigo", hex: "#6A5AE0"),
        .init(name: "Purple", hex: "#A55EEA"),
        .init(name: "Pink", hex: "#EC5B9A"),
        .init(name: "Red", hex: "#EF5B5B"),
        .init(name: "Orange", hex: "#F28C38"),
        .init(name: "Yellow", hex: "#F2C230"),
        .init(name: "Green", hex: "#3DBE7A"),
        .init(name: "Teal", hex: "#2BB3B1"),
        .init(name: "Graphite", hex: "#6E7681"),
    ]

    static func forSeed(_ seed: String) -> Swatch {
        var h: UInt64 = 5381
        for b in seed.utf8 { h = (h &* 33) &+ UInt64(b) }
        return hues[Int(h % UInt64(hues.count))]
    }

    /// The first color no bot uses yet, so a new bot stands apart from the team.
    static func firstUnused(by colors: [String?]) -> Swatch {
        let taken = Set(colors.compactMap { $0?.uppercased() })
        return hues.first { !taken.contains($0.hex) } ?? hues[0]
    }
}

nonisolated extension NSColor {
    /// Reads "#RRGGBB" or "RRGGBB".
    convenience init?(hexString: String) {
        var s = hexString.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#") { s.removeFirst() }
        guard s.count == 6, let value = UInt32(s, radix: 16) else { return nil }
        self.init(
            srgbRed: CGFloat((value >> 16) & 0xFF) / 255,
            green: CGFloat((value >> 8) & 0xFF) / 255,
            blue: CGFloat(value & 0xFF) / 255,
            alpha: 1
        )
    }

    /// "#RRGGBB" in sRGB.
    var hexString: String {
        let c = usingColorSpace(.sRGB) ?? self
        let v = [c.redComponent, c.greenComponent, c.blueComponent].map { min(max(Int(($0 * 255).rounded()), 0), 255) }
        return String(format: "#%02X%02X%02X", v[0], v[1], v[2])
    }
}

/// A row of swatches, plus the system color panel for anything else.
struct BotColorPicker: View {
    @Binding var hex: String

    private var isCustom: Bool { !BotColors.all.contains { $0.hex.caseInsensitiveCompare(hex) == .orderedSame } }

    var body: some View {
        HStack(spacing: 6) {
            ForEach(BotColors.all) { swatch in
                let selected = swatch.hex.caseInsensitiveCompare(hex) == .orderedSame
                Button { hex = swatch.hex } label: {
                    swatchDot(swatch)
                        .frame(width: 18, height: 18)
                        .padding(2.5)
                        .overlay(Circle().strokeBorder(selected ? Color.primary.opacity(0.55) : .clear, lineWidth: 1.5))
                }
                .buttonStyle(.plain)
                .help(BotColors.isMono(swatch.hex) ? "Black & White: black in light mode, white in dark mode" : swatch.name)
                .accessibilityLabel(swatch.name)
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
            ColorPicker(
                "Custom",
                selection: Binding(
                    get: { Color(nsColor: NSColor(hexString: hex) ?? .systemBlue) },
                    set: { hex = NSColor($0).hexString }
                ),
                supportsOpacity: false
            )
            .labelsHidden()
            .help("Custom color")
            .overlay(Circle().strokeBorder(isCustom ? Color.primary.opacity(0.55) : .clear, lineWidth: 1.5).allowsHitTesting(false).padding(-3))
        }
    }

    /// A plain dot, or for Black & White a dot split diagonally, so it reads as
    /// "changes with the mode" whichever mode you're in.
    @ViewBuilder
    private func swatchDot(_ swatch: BotColors.Swatch) -> some View {
        if BotColors.isMono(swatch.hex) {
            Circle()
                .fill(Color.black)
                .overlay {
                    Circle().fill(Color.white).mask {
                        Path { p in
                            p.move(to: .zero)
                            p.addLine(to: CGPoint(x: 18, y: 0))
                            p.addLine(to: CGPoint(x: 0, y: 18))
                            p.closeSubpath()
                        }
                    }
                }
                .overlay(Circle().strokeBorder(Color.primary.opacity(0.2), lineWidth: 0.5))
        } else {
            Circle().fill(Color(nsColor: NSColor(hexString: swatch.hex)!))
        }
    }
}
