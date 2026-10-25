"""Render skinned companion clips with fixed framing and pose-space loop seams."""
import bpy, math, json, argparse, sys
from pathlib import Path
from mathutils import Matrix
parser=argparse.ArgumentParser()
parser.add_argument('--scene',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
OUT=args.output;OUT.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(args.scene))
s=bpy.context.scene;arm=next(o for o in s.objects if o.type=='ARMATURE')
s.render.resolution_x=192;s.render.resolution_y=288;s.render.resolution_percentage=100
s.render.image_settings.file_format='PNG';s.render.image_settings.color_mode='RGBA';s.render.film_transparent=True
s.camera.data.ortho_scale=2.44
clips={
 'idle':('Default_Wait',25,50,True),
 'greeting':('Default_Joy_Hello',18,36,False),
 'fidget':('Default_Wait_Random',128,255,False),
 'listening':('Default_Normal_Talk_Wait',35,70,True),
 'thinking':('Default_Think_Talk_Wait',30,60,True),
 'reply':('Default_Normal_Talk',25,49,True),
 'welcome':('Default_Normal_Hello',30,60,False),
 'ponder':('Default_Think_Hello',27,54,False),
 'explain':('Default_Think_Talk',30,60,True),
 'cheerful':('Default_Joy_Talk',25,50,True),
 'relaxed':('Default_Joy_Talk_Wait',40,50,False),
 'surprised':('Default_Surprised_Talk_Hello',15,30,False),
}
missing=set(v[0] for v in clips.values())-set(bpy.data.actions.keys())
if missing:raise ValueError('Scene is missing baked native actions: '+', '.join(sorted(missing)))
def pose(action,frame):
 arm.animation_data.action=bpy.data.actions[action]
 s.frame_set(int(frame),subframe=frame-int(frame))
 return {b.name:b.matrix_basis.copy() for b in arm.pose.bones}
idle=pose('Default_Wait',1)
def mix(a,b,t):
 # Quaternion interpolation avoids scaling/shearing fingers or limb joints.
 pa,ra,sa=a.decompose();pb,rb,sb=b.decompose()
 return Matrix.LocRotScale(pa.lerp(pb,t),ra.slerp(rb,t),sa.lerp(sb,t))
def smooth(t):return t*t*(3-2*t)
manifest={'version':1,'width':192,'height':288,'columns':8,'fps':15,'clips':{}}
for name,(action,count,duration,loop) in clips.items():
 folder=OUT/name;folder.mkdir(exist_ok=True)
 first=pose(action,1)
 for i in range(count):
  f=1+duration*i/count
  matrices=pose(action,f)
  # Original loops are eased into the first pose over their final four samples.
  if loop and i>=count-4:
   amount=smooth((i-(count-4))/4)
   matrices={n:mix(m,first[n],amount) for n,m in matrices.items()}
  # One-shot gestures depart from and return to the same idle pose. A 4-frame
  # ramp is enough for the lightweight dock without snapping arms at boundaries.
  if not loop:
   strength=smooth(min(1,i/4,(count-1-i)/4))
   matrices={n:mix(idle[n],m,strength) for n,m in matrices.items()}
  arm.animation_data.action=None
  for n,m in matrices.items():arm.pose.bones[n].matrix_basis=m
  bpy.context.view_layer.update()
  s.render.filepath=str(folder/f'{i:03d}.png');bpy.ops.render.render(write_still=True)
 manifest['clips'][name]={'file':name+'.png','frames':count,'loop':loop,'fps':15,'source_action':action}
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
 print('CLIP_DONE',name,count,flush=True)
print('COMPANION_ACTIONS_DONE',sum(v[1] for v in clips.values()),flush=True)
