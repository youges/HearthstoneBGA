"""Conservative detectors for the calibrated 16:9 PC board, no input here."""
import cv2
import numpy as np
import re
from .model import State


def count(mask,x1,y1,x2,y2):
    return cv2.countNonZero(mask[y1:y2,x1:x2])


def hand_card_mark(frame,point):
    """Describe visible artwork at a candidate, independently of other cards."""
    x,y=round(point[0]*1536),round(point[1]*864)
    patch=frame[max(0,y-16):min(864,y+16),max(0,x-24):min(1536,x+24)]
    if patch.shape[:2]!=(32,48) or max(patch.reshape(-1,3).std(axis=0))<5:return None
    small=cv2.resize(cv2.GaussianBlur(patch,(5,5),0),(8,6),interpolation=cv2.INTER_AREA)
    return tuple(int(n) for n in small.ravel())


def hero_power_choice_point(image):
    """Locate a complete selectable power card under a verified choice title.

    Hovering enlarges and recolors a card, so use the leftmost complete green
    outline rather than a fixed center or a count of all visible cards.
    """
    frame=cv2.resize(image,(1536,864),interpolation=cv2.INTER_AREA)
    green=cv2.inRange(cv2.cvtColor(frame,cv2.COLOR_BGR2HSV),(40,110,120),(85,255,255))
    # A gold mana crest can split a card's top glow into two components.
    # Pair long upright edges instead of joining across nearby shop artwork.
    top,bottom=285,490
    columns=np.mean(green[top:bottom]>0,axis=0)>.70
    edges=np.diff(np.r_[False,columns,False].astype(np.int8))
    runs=[(int(a),int(b)) for a,b in zip(np.where(edges==1)[0],np.where(edges==-1)[0])
          if 280<=a and b<=1260 and 2<=b-a<=30]
    for (left,le),(right,re) in zip(runs,runs[1:]):
        x1,x2=(left+le)/2,(right+re)/2
        if 230<=x2-x1<=285:
            density=np.mean(green[top:bottom,le:right]>0)
            if density<.35:
                return (float(x1+x2)/2/1536,float(top+bottom)/2/864)
    return None


def two_spell_choice_cards(image):
    """Find two large selectable card outlines above a still-visible tavern.

    Some battlecries offer cards without a choice title or minion-tier corner.
    Both complete, aligned outlines are required; text and card artwork alone
    never authorize selection. Coordinates are normalized to the client area.
    """
    frame=cv2.resize(image,(1536,864),interpolation=cv2.INTER_AREA)
    green=cv2.inRange(cv2.cvtColor(frame,cv2.COLOR_BGR2HSV),(40,110,120),(85,255,255))
    # The mana gem breaks the left glow into separate pieces. Close small gaps,
    # then verify the original pixels along both upright edges of each card.
    connected=cv2.morphologyEx(green,cv2.MORPH_CLOSE,np.ones((21,21),np.uint8))
    _,_,stats,_=cv2.connectedComponentsWithStats(connected)
    cards=[]
    for x,y,w,h,area in stats[1:]:
        if not (350<=x and x+w<=1190 and 220<=y<=310
                and 225<=w<=295 and 260<=h<=330 and .06<=area/(w*h)<=.40):
            continue
        left=np.any(green[y:y+h,x:x+35],axis=1).mean()
        right=np.any(green[y:y+h,x+w-35:x+w],axis=1).mean()
        if min(left,right)<.70:
            continue
        cards.append((int(x),int(y),int(w),int(h)))
    if len(cards)!=2:
        return None
    cards.sort()
    (x1,y1,w1,h1),(x2,y2,w2,h2)=cards
    c1,c2=x1+w1/2,x2+w2/2
    if not (500<=c1<=650 and 885<=c2<=1035 and abs(c1+c2-1536)<=45
            and abs(y1-y2)<=15 and abs(h1-h2)<=20 and abs(w1-w2)<=30):
        return None
    return [(float(x+w/2)/1536,float(y+h/2)/864) for x,y,w,h in cards]


def shop_spell_cost(ocr,roi):
    if not hasattr(ocr,'recognize_line'):return None
    def read(image):
        values={int(t.text) for t in ocr.recognize_line(image)
                if t.score>=.90 and re.fullmatch(r'\d',t.text)}
        return values.pop() if len(values)==1 else None
    value=read(roi)
    if value is not None:return value
    # Small green discounted prices are often correct but low-confidence at
    # native scale. Two enlarged readings must independently agree.
    large=read(cv2.resize(roi,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC))
    wide=read(cv2.resize(roi,None,fx=4,fy=3,interpolation=cv2.INTER_CUBIC))
    if large is not None and large==wide:return large
    narrow=read(cv2.resize(roi,None,fx=2,fy=3,interpolation=cv2.INTER_CUBIC))
    tall=read(cv2.resize(roi,None,fx=2,fy=4,interpolation=cv2.INTER_CUBIC))
    return narrow if narrow is not None and narrow==tall else None


def shop_price_badge(vision,frame,x):
    key='pc_shop_price_badge'
    if key not in vision.cache:
        path=vision.root/'assets/templates/live/shop-price-badge.png'
        vision.cache[key]=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR) if path.exists() else None
    template=vision.cache[key]
    if template is None:return False
    # Ignore the price digit and compare only the round gold rim. Gold minion
    # artwork and triple highlights must not count as a price badge.
    mask=np.zeros(template.shape[:2],np.uint8)
    cv2.ellipse(mask,(14,17),(13,14),0,0,360,255,-1)
    cv2.ellipse(mask,(14,17),(9,11),0,0,360,0,-1)
    scores=cv2.matchTemplate(frame[262:300,x-57:x-23],template,cv2.TM_CCOEFF_NORMED,mask=mask)
    scores=scores[np.isfinite(scores)]
    return bool(scores.size and scores.max()>=.70)


def board_count(frame,empty):
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    glow=cv2.inRange(hsv,(85,90,170),(135,255,255))
    if cv2.countNonZero(glow[550:590,340:1190])>100:
        return None
    delta=np.max(cv2.absdiff(frame,empty),axis=2)
    difference=delta>55
    fine_difference=delta>25
    area=difference[415:550,340:1190]
    if area.mean()<.045:
        return 0
    fits=[]
    for n in range(1,8):
        xs=[768+(i-(n-1)/2)*112 for i in range(n)]
        core=min(difference[425:490,int(x-25):int(x+25)].mean() for x in xs)
        fine_core=min(fine_difference[425:490,int(x-25):int(x+25)].mean() for x in xs)
        outside=area.copy()
        for x in xs:
            outside[:,max(0,int(x-49)-340):min(850,int(x+49)-340)]=False
        # Gold/shielded minions can resemble the empty tavern's brown pixels.
        # Use finer color differences only when almost all strong changes fit
        # the slot row; animation and tooltip rejection still runs first.
        if (core>=.55 and outside.mean()<.08) or (fine_core>=.65 and outside.mean()<.04):
            fits.append(n)
    return fits[0] if len(fits)==1 else None


def components(mask,area=85):
    _,_,stats,centers=cv2.connectedComponentsWithStats(mask)
    return [(int(x),int(y),w,h) for (x,y),(_,_,w,h,a) in zip(centers[1:],stats[1:])
            if area<a<1300 and 12<h<42 and 12<w<42]


def count_tavern_stars(frame):
    roi=frame[151:204,683:731]
    mask=cv2.inRange(cv2.cvtColor(roi,cv2.COLOR_BGR2HSV),(18,110,120),(40,255,255))
    _,_,stats,centers=cv2.connectedComponentsWithStats(mask)
    stars=[(x,y,a) for (_,_,w,h,a),(x,y) in zip(stats[1:],centers[1:])
           if 25<a<105 and 6<=w<=16 and 6<=h<=16 and 4<x<44 and 7<y<46]
    n=len(stars)
    if not 1<=n<=6:return None
    rows=[]
    for x,y,a in sorted(stars,key=lambda s:s[1]):
        row=next((r for r in rows if abs(r[0]-y)<5),None)
        if row is None:rows.append([y,1])
        else:row[1]+=1
    expected={1:[1],2:[2],3:[2,1],4:[2,2],5:[2,1,2],6:[2,2,2]}
    return n if [r[1] for r in rows]==expected[n] else None


def targeting_arrow(frame):
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,(0,150,130),(8,255,255))|cv2.inRange(hsv,(172,150,130),(180,255,255))
    roi=mask[250:550,340:1460]
    joined=cv2.morphologyEx(roi,cv2.MORPH_CLOSE,np.ones((13,13),np.uint8))
    _,_,stats,_=cv2.connectedComponentsWithStats(joined)
    return any(w>180 and h>12 and area>600 and w>h*1.5 for _,_,w,h,area in stats[1:])


def highlighted_friendly_target(frame):
    return _highlighted_minion_target(frame,408)


def highlighted_shop_target(frame):
    return _highlighted_minion_target(frame,252)


def _highlighted_minion_target(frame,top):
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    orange=cv2.inRange(hsv,(7,140,170),(35,255,255))
    ring=np.zeros((136,106),np.uint8)
    cv2.ellipse(ring,(53,68),(46,62),0,0,360,255,7)
    masks=[]
    for region in [(slice(0,70),slice(None)),(slice(45,105),slice(0,38)),(slice(45,105),slice(68,106))]:
        mask=np.zeros_like(ring);mask[region]=ring[region];masks.append(mask)
    best=(0,None)
    for x in range(380,1151,2):
        roi=orange[top:top+136,x-53:x+53]
        score=min(cv2.countNonZero(cv2.bitwise_and(roi,m))/cv2.countNonZero(m) for m in masks)
        if score>best[0]:best=(score,x)
    return (best[1]/1536,(top+68)/864) if best[0]>.24 else None


def apply_pc_layout(vision,image,obs):
    frame=cv2.resize(image,(1536,864),interpolation=cv2.INTER_AREA)
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    purple=cv2.inRange(hsv,(125,110,50),(175,255,255))
    if obs.state==State.CHOICE:
        obs.metrics.setdefault('choice_targeted',int(bool(re.search(r'使一个随从获|选择一个随从',obs.evidence))))
        if '饰品商店' in obs.evidence:
            blue=cv2.inRange(hsv,(85,90,150),(120,255,255))
            obs.metrics['choice_confirm_ready']=int(count(blue,704,563,835,636)>600)
        return
    if obs.state==State.HERO:
        green=cv2.inRange(hsv,(40,110,120),(85,255,255))
        for slot,x in [(2,638),(3,913)]:
            # Locked outer slots are never candidates. Purple nameplate is
            # positive evidence; gray plates have virtually no purple pixels.
            if count(purple,x-85,462,x+85,519)>3500:
                obs.available_heroes.append(slot)
                border=count(green,x-106,255,x-85,455)+count(green,x+85,255,x+106,455)
                if border>400:
                    obs.metrics['hero_selected_slot']=slot
        return
    if obs.state!=State.RECRUIT:
        return
    empty=vision.cache.get('pc_empty_board')
    if empty is None:
        empty=cv2.imdecode(np.fromfile(vision.root/'assets/templates/live/empty-board-frame.png',dtype=np.uint8),cv2.IMREAD_COLOR)
        if empty is None: return
        empty=cv2.resize(empty,(1536,864))
        vision.cache['pc_empty_board']=empty
    obs.board_count=board_count(frame,empty)
    obs.metrics['targeting_arrow']=int(targeting_arrow(frame))
    if obs.board_count:
        obs.targets['friendly_target']=((768-(obs.board_count-1)*56)/1536,470/864)
    if obs.metrics['targeting_arrow']:
        target=highlighted_friendly_target(frame)
        if target:
            if obs.board_count:
                centers=[(768+(i-(obs.board_count-1)/2)*112)/1536 for i in range(obs.board_count)]
                target=(min(centers,key=lambda x:abs(x-target[0])),470/864)
            else:
                obs.targets['friendly_target']=target
            obs.targets['highlighted_friendly_target']=target
            obs.metrics['friendly_target_verified']=1
        shop_target=highlighted_shop_target(frame)
        if shop_target:
            obs.targets['shop_spell_target']=shop_target
            obs.metrics['shop_target_verified']=1
    tier_scores=[]
    for tier in range(1,7):
        name=f'pc_tier_{tier}'
        if name not in vision.cache:
            path=vision.root/f'assets/templates/live/tier-{tier}.png'
            vision.cache[name]=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR) if path.exists() else None
        patch=vision.cache[name]
        roi=frame[151:204,683:731]
        if patch is not None:
            score=float(cv2.matchTemplate(roi,patch,cv2.TM_CCOEFF_NORMED).max())
            tier_scores.append((score,tier))
    tier_scores.sort(reverse=True)
    if tier_scores and tier_scores[0][0]>.82 and (len(tier_scores)<2 or tier_scores[0][0]-tier_scores[1][0]>.10):
        obs.metrics['tavern_tier']=tier_scores[0][1]
    stars=count_tavern_stars(frame)
    if stars is not None:
        obs.metrics['tavern_tier']=stars
    red=cv2.inRange(hsv,(0,145,130),(8,255,255))|cv2.inRange(hsv,(172,145,130),(180,255,255))
    gold=cv2.inRange(hsv,(15,100,135),(38,255,255))
    flags=purple.copy();flags[:238]=0;flags[281:]=0;flags[:,:400]=0;flags[:,1150:]=0
    shop_flags=sorted(components(flags))
    obs.metrics['shop_card_count']=len(shop_flags)
    for i,(x,y,_,_) in enumerate(shop_flags,1):
        # Spell artwork can resemble lower stat badges. Its upper price badge
        # takes precedence; an unreadable price must not become a minion.
        has_price_badge=count(gold,x-55,264,x-25,298)>20 and shop_price_badge(vision,frame,x)
        if not has_price_badge and count(red,x+15,341,x+48,381)>20 and count(gold,x-43,341,x-12,377)>40:
            name=f'shop_{i}';obs.targets[name]=(x/1536,320/864);obs.shop_minions.append(name)
        elif getattr(vision,'inspect_shop_spells',False) and has_price_badge:
            roi=frame[266:296,x-54:x-27]
            cost=shop_spell_cost(vision.ocr,roi)
            if cost is not None:
                name=f'spell_shop_{i}';obs.targets[name]=(x/1536,320/864)
                obs.shop_spells.append(name);obs.metrics[name+'_cost']=cost
    hand=purple.copy();hand[:730]=0;hand[815:]=0;hand[:,:400]=0;hand[:,1100:]=0
    green=cv2.inRange(hsv,(40,110,120),(85,255,255))
    for i,(x,y,_,_) in enumerate(sorted(components(hand,100)),1):
        if count(gold,x-10,y-12,x+10,y+12)<8:
            continue
        if count(green,x-15,y-15,x+110,835)<180 or count(green,x,y-5,x+100,y+20)<40:
            continue
        name=f'hand_{i}';obs.targets[name]=((x+30)/1536,min(y+45,835)/864);obs.hand_minions.append(name)
        obs.hand_priority.append(name)
    # Generated spells (e.g. Bananas) have no purple tavern-tier flag. Their
    # playable green card outline supplies a hover candidate, never a cast
    # authorization: the engine must still read the description first.
    _,_,stats,_=cv2.connectedComponentsWithStats(green[730:835,400:1100])
    for i,(x,y,w,h,area) in enumerate(stats[1:],1):
        if not (60<=w<=145 and h>=40 and area>=300 and y<65):continue
        point=((400+x+w/2)/1536,min(730+y+50,835)/864)
        if any(abs(obs.targets[n][0]-point[0])<.035 for n in obs.hand_minions):continue
        name=f'hand_green_{i}';obs.targets[name]=point;obs.hand_minions.append(name)
    obs.hand_minions.sort(key=lambda name:obs.targets[name][0])
    for name in obs.hand_minions:
        mark=hand_card_mark(frame,obs.targets[name])
        if mark is not None:obs.hand_marks[name]=mark
    obs.metrics['hand_count']=len(obs.hand_minions)
