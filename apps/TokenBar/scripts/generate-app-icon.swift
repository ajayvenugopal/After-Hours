import AppKit
import Foundation

// Run from the project root, then convert Resources/AppIcon.iconset with iconutil.
let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent("Resources")
let iconset = root.appendingPathComponent("AppIcon.iconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

func render(size: Int) -> Data {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    let scale = NSAffineTransform()
    scale.scale(by: CGFloat(size) / 1024); scale.concat()
    NSColor(calibratedRed: 0.08, green: 0.43, blue: 0.37, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: 32, y: 32, width: 960, height: 960), xRadius: 210, yRadius: 210).fill()
    for (index, height) in [220.0, 360.0, 520.0].enumerated() {
        NSColor(calibratedWhite: 1, alpha: index == 0 ? 0.65 : index == 1 ? 0.82 : 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: 256 + Double(index) * 192, y: 244, width: 128, height: height), xRadius: 42, yRadius: 42).fill()
    }
    NSGraphicsContext.restoreGraphicsState()
    return bitmap.representation(using: .png, properties: [:])!
}

for size in [16, 32, 128, 256, 512] {
    try render(size: size).write(to: iconset.appendingPathComponent("icon_\(size)x\(size).png"))
    try render(size: size * 2).write(to: iconset.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
try render(size: 1024).write(to: root.appendingPathComponent("AppIcon.png"))
