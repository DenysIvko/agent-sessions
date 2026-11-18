import AppKit

let folder = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                                      bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                      colorSpaceName: .deviceRGB, bytesPerRow: pixels * 4, bitsPerPixel: 32)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
        let bounds = NSRect(x: 0, y: 0, width: pixels, height: pixels)
        NSColor(calibratedRed: 0.055, green: 0.063, blue: 0.078, alpha: 1).setFill()
        NSBezierPath(roundedRect: bounds.insetBy(dx: Double(pixels) * 0.04, dy: Double(pixels) * 0.04),
                     xRadius: Double(pixels) * 0.2, yRadius: Double(pixels) * 0.2).fill()
        for index in 0..<4 {
            let x = Double(pixels) * (index % 2 == 0 ? 0.22 : 0.54)
            let y = Double(pixels) * (index < 2 ? 0.54 : 0.22)
            (index % 2 == 0 ? NSColor(calibratedRed: 0.49, green: 0.83, blue: 0.76, alpha: 1)
                : NSColor(calibratedRed: 0.90, green: 0.63, blue: 0.53, alpha: 1)).setFill()
            NSBezierPath(roundedRect: NSRect(x: x, y: y, width: Double(pixels) * 0.24, height: Double(pixels) * 0.24),
                         xRadius: Double(pixels) * 0.04, yRadius: Double(pixels) * 0.04).fill()
        }
        NSGraphicsContext.restoreGraphicsState()
        let name = "icon_\(size)x\(size)\(scale == 2 ? "@2x" : "").png"
        try bitmap.representation(using: .png, properties: [:])!.write(to: folder.appendingPathComponent(name))
    }
}
