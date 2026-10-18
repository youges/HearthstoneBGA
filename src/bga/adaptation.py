"""Pure physical-pixel geometry shared by the native adapter and offline tests."""
import math


def fit_client(work_area, border, aspect, minimum=(960,540)):
    left,top,right,bottom=work_area
    bx,by=border
    if not math.isfinite(aspect) or not .7<=aspect<=4:
        raise ValueError('校准宽高比无效')
    available_w,available_h=right-left-bx-16,bottom-top-by-16
    width=min(available_w,math.floor(available_h*aspect))
    height=math.floor(width/aspect)
    if width<minimum[0] or height<minimum[1]:
        raise ValueError(f'屏幕可用空间不足，客户区至少需要 {minimum[0]}×{minimum[1]} 物理像素；请降低显示缩放或使用更大屏幕')
    outer_w,outer_h=width+bx,height+by
    return (left+(right-left-outer_w)//2,top+(bottom-top-outer_h)//2,outer_w,outer_h)


def needs_fit(client_rect,outer_rect,work_area,aspect):
    _,_,width,height=client_rect
    left,top,right,bottom=outer_rect
    wl,wt,wr,wb=work_area
    return (abs(width/height/aspect-1)>.01 or width<960 or height<540
            or left<wl or top<wt or right>wr or bottom>wb)
