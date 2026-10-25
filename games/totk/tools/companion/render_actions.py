"""Render skinned companion clips with fixed framing and pose-space loop seams."""
import bpy, math, json, argparse, sys
from pathlib import Path
from mathutils import Matrix
parser=argparse.ArgumentParser()
parser.add_argument('--scene',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--only',help='Comma-separated clips; merge existing manifest for incremental rendering')
parser.add_argument('--width',type=int,default=192,help='Canvas width; height and camera scale stay fixed')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
OUT=args.output;OUT.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(args.scene))
s=bpy.context.scene;arm=next(o for o in s.objects if o.type=='ARMATURE')
s.render.resolution_x=args.width;s.render.resolution_y=288;s.render.resolution_percentage=100
s.render.image_settings.file_format='PNG';s.render.image_settings.color_mode='RGBA';s.render.film_transparent=True
s.camera.data.ortho_scale=2.44
clips={
 'walk':('Default_Move_Walk',18,36,True),
 'run':('Common_Move_Run',10,20,True),
 'combat':('Combat_Wait',20,40,True),
 'combat_run':('Common_Move_Run',10,20,True),
 'attack':('Combat_Attack',24,50,False),
 'jump':('Jump_St',6,4,False),
 'fall':('Jump_Ed',6,4,False),
 'land':('Jump_Ed',8,11,False),
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
if args.only:clips={k:v for k,v in clips.items() if k in args.only.split(',')}
missing=set(v[0] for v in clips.values())-set(bpy.data.actions.keys())
if missing:raise ValueError('Scene is missing baked native actions: '+', '.join(sorted(missing)))
def pose(action,frame):
 arm.animation_data.action=bpy.data.actions[action]
 s.frame_set(int(frame),subframe=frame-int(frame))
 return {b.name:b.matrix_basis.copy() for b in arm.pose.bones}
idle=pose('Default_Wait',1)
base_arm_location=arm.location.copy()
def mesh_floor():
 deps=bpy.context.evaluated_depsgraph_get()
 return min((o.matrix_world @ v.co).z for o in s.objects if o.type=='MESH' and not o.get('companion_weapon') for v in o.evaluated_get(deps).data.vertices)
base_floor=mesh_floor()
def mix(a,b,t):
 # Quaternion interpolation avoids scaling/shearing fingers or limb joints.
 pa,ra,sa=a.decompose();pb,rb,sb=b.decompose()
 return Matrix.LocRotScale(pa.lerp(pb,t),ra.slerp(rb,t),sa.lerp(sb,t))
def smooth(t):return t*t*(3-2*t)
manifest={'version':1,'width':192,'height':288,'columns':8,'fps':15,'clips':{}}
if args.only and (OUT/'manifest.json').exists():manifest=json.loads((OUT/'manifest.json').read_text())
for name,(action,count,duration,loop) in clips.items():
 for ob in s.objects:
  if ob.get('companion_weapon'):ob.hide_render=name not in ('combat','combat_run','attack')
 folder=OUT/name;folder.mkdir(exist_ok=True)
 first=pose(action,1)
 for i in range(count):
  f=1+duration*i/count
  if name=='jump':f=1+4*min(1,i/3)
  if name=='fall':f=1+i/(count-1)
  if name=='land':f=2+14*i/(count-1)
  matrices=pose(action,f)
  if name=='jump' and i>=3:
   target=pose('Jump',1)
   matrices={n:mix(m,target[n],smooth((i-3)/2)) for n,m in matrices.items()}
  if name in ('walk','run','combat_run','attack'):
   matrices['Root']=idle['Root'].copy()  # Remove travel; retain the authored limb cycle.
  # Original loops are eased into the first pose over their final four samples.
  if loop and i>=count-4:
   amount=smooth((i-(count-4))/4)
   matrices={n:mix(m,first[n],amount) for n,m in matrices.items()}
  # One-shot gestures depart from and return to the same idle pose. A 4-frame
  # ramp is enough for the lightweight dock without snapping arms at boundaries.
  if not loop and name not in ('jump','fall','land','attack'):
   strength=smooth(min(1,i/4,(count-1-i)/4))
   matrices={n:mix(idle[n],m,strength) for n,m in matrices.items()}
  arm.animation_data.action=None
  for n,m in matrices.items():arm.pose.bones[n].matrix_basis=m
  arm.location=base_arm_location.copy();bpy.context.view_layer.update()
  if name=='attack':
   # Native slash contains a travelling hop in the pelvis. Anchor the dock's
   # body floor; retain the authored knees, shoulders and sword arcs.
   arm.location.z+=base_floor-mesh_floor();bpy.context.view_layer.update()
  elif name in ('walk','run','combat','combat_run','land'):
   arm.location.z+=max(0,base_floor-mesh_floor());bpy.context.view_layer.update()
  s.render.filepath=str(folder/f'{i:03d}.png');bpy.ops.render.render(write_still=True)
 manifest['clips'][name]={'file':name+'.png','frames':count,'loop':loop,'fps':30 if name in ('jump','fall','land','attack') else 15,'source_action':action,'width':args.width}
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
 print('CLIP_DONE',name,count,flush=True)
print('COMPANION_ACTIONS_DONE',sum(v[1] for v in clips.values()),flush=True)
