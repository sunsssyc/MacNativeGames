import Foundation
import CoreGraphics
import ImageIO
let root=URL(fileURLWithPath:CommandLine.arguments[1])
let data=try Data(contentsOf:root.appendingPathComponent("manifest.json"))
let manifest=try JSONSerialization.jsonObject(with:data) as! [String:Any]
let w=manifest["width"] as! Int,h=manifest["height"] as! Int,cols=manifest["columns"] as! Int
let clips=manifest["clips"] as! [String:[String:Any]]
for (name,clip) in clips {
 let count=clip["frames"] as! Int,rows=(count+cols-1)/cols
 let ctx=CGContext(data:nil,width:w*cols,height:h*rows,bitsPerComponent:8,bytesPerRow:0,space:CGColorSpace(name:CGColorSpace.sRGB)!,bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue)!
 for i in 0..<count {
  let path=root.appendingPathComponent(name).appendingPathComponent(String(format:"%03d.png",i))
  let source=CGImageSourceCreateWithURL(path as CFURL,nil)!
  let image=CGImageSourceCreateImageAtIndex(source,0,nil)!
  precondition(image.width==w && image.height==h)
  ctx.draw(image,in:CGRect(x:(i%cols)*w,y:(rows-1-i/cols)*h,width:w,height:h))
 }
 let dst=CGImageDestinationCreateWithURL(root.appendingPathComponent(name+".png") as CFURL,"public.png" as CFString,1,nil)!
 CGImageDestinationAddImage(dst,ctx.makeImage()!,nil);precondition(CGImageDestinationFinalize(dst))
 print("PACKED",name,count)
}
