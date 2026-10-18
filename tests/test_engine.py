import pytest

from bga.engine import NeedsAttention
from bga.model import Observation, State
from conftest import settle


def test_brief_late_turn_animation_gets_a_fresh_recovery_window(world,targets):
    engine,_,clock=world
    known=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':6},board_count=3)
    settle(engine,clock,known)
    clock.advance(60)
    unknown=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':6},board_count=None)
    settle(engine,clock,unknown)
    assert engine.decide(unknown) is None
    clock.advance(21)
    assert engine.decide(unknown) is None
    clock.advance(30)
    assert engine.decide(unknown) is None
    combat=Observation(State.COMBAT,.99,True,targets)
    settle(engine,clock,combat)
    assert engine.decide(combat) is None
    settle(engine,clock,known)
    settle(engine,clock,unknown)
    assert engine.decide(unknown) is None


def test_concede_animation_never_triggers_more_game_actions(world,targets):
    engine,_,clock=world
    engine.concede_sent=True
    obs=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':10,'upgrade_cost':1,'tavern_tier':1},
                    hand_minions=['hand_1'],shop_minions=['shop_1'],board_count=0)
    settle(engine,clock,obs,4)
    assert engine.decide(obs) is None


def test_targeted_choice_waits_for_arrow_and_known_friendly(world,targets):
    engine,_,clock=world
    choice=Observation(State.CHOICE,.99,True,targets,metrics={'choice_targeted':1})
    settle(engine,clock,choice)
    select=engine.decide(choice);assert select.target=='choice_1'
    engine.sent(select,choice)
    recruit=Observation(State.RECRUIT,.99,True,dict(targets,friendly_target=(.4,.54)),
                        metrics={'targeting_arrow':0},board_count=3)
    settle(engine,clock,recruit)
    assert engine.decide(recruit) is None
    recruit.metrics['targeting_arrow']=1
    recruit.board_count=None
    settle(engine,clock,recruit)
    assert engine.decide(recruit) is None
    recruit.board_count=3
    settle(engine,clock,recruit)
    target=engine.decide(recruit);assert target.target=='friendly_target'
    engine.sent(target,recruit)
    assert not engine.feedback(target,recruit,recruit)
    after=Observation(State.RECRUIT,.99,True,targets,metrics={'targeting_arrow':0},board_count=3)
    assert engine.feedback(target,recruit,after)
    assert not engine.feedback(target,recruit,Observation(State.COMBAT,.99,True))


def test_hand_buff_is_inspected_then_revalidated_before_target_drag(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    t=dict(targets,hand_1=(.45,.9),friendly_target=(.4,.54))
    obs=Observation(State.RECRUIT,.99,True,t,metrics={'gold':0,'hand_count':1},board_count=2,hand_minions=['hand_1'])
    settle(engine,clock,obs)
    hover=engine.decide(obs);assert hover.kind=='hover'
    engine.sent(hover,obs);clock.advance(1)
    obs.metrics['hand_card_kind']='buff';obs.targets['inspected_hand']=(.45,.9)
    settle(engine,clock,obs)
    clear=engine.decide(obs);assert clear.target=='clear_tooltip'
    engine.sent(clear,obs);settle(engine,clock,obs)
    use=engine.decide(obs)
    assert use.kind=='drag' and use.target=='inspected_hand' and use.destination=='friendly_target'
    engine.sent(use,obs)
    assert not engine.feedback(use,obs,obs)
    after=Observation(State.RECRUIT,.99,True,t,metrics={'gold':0,'hand_count':0},board_count=2)
    settle(engine,clock,after)
    assert engine.feedback(use,obs,after)


def test_full_board_sale_needs_feedback_then_plays_the_inspected_minion(world,targets):
    engine,_,clock=world
    engine.config.inspect_hand_cards=True;engine.config.auto_sell_for_space=True
    t=dict(targets,hand_1=(.45,.9),friendly_target=(.28,.54),tavernkeeper=(.5,.19))
    obs=Observation(State.RECRUIT,.99,True,t,metrics={'gold':2,'hand_count':1},board_count=7,hand_minions=['hand_1'])
    settle(engine,clock,obs)
    hover=engine.decide(obs);engine.sent(hover,obs)
    obs.metrics['hand_card_kind']='minion';settle(engine,clock,obs)
    clear=engine.decide(obs);engine.sent(clear,obs);settle(engine,clock,obs)
    sale=engine.decide(obs)
    assert sale.target=='sell_minion' and sale.destination=='tavernkeeper'
    engine.sent(sale,obs)
    assert not engine.feedback(sale,obs,obs)
    after=Observation(State.RECRUIT,.99,True,t,metrics={'gold':3,'hand_count':1},board_count=7,hand_minions=['hand_1'])
    settle(engine,clock,after)
    assert not engine.feedback(sale,obs,after)  # Gold alone cannot prove a sale.
    after.board_count=6;settle(engine,clock,after)
    assert engine.feedback(sale,obs,after)
    play=engine.decide(after)
    assert play.target=='inspected_hand' and play.destination=='board_drop'
    assert engine.sold_for_space
    engine.sent(play,after)
    again=Observation(State.RECRUIT,.99,True,t,metrics={'gold':3,'hand_count':0},board_count=7)
    settle(engine,clock,again)
    engine.decide(again)
    again.hand_minions=['hand_1'];again.metrics['hand_count']=1
    settle(engine,clock,again)
    engine.hand_probe={'point':(.45,.9),'count':1,'stage':'ready','kind':'minion','source':'hand'}
    assert engine.decide(again) is None  # Never churn a second slot this turn.
    settle(engine,clock,Observation(State.COMBAT,.99,True,t))
    assert not engine.sold_for_space


@pytest.mark.parametrize('enabled,board,kind',[(False,7,'minion'),(True,None,'minion'),(True,7,'unknown')])
def test_auto_sale_is_not_authorized_by_an_unknown_board_or_card(world,targets,enabled,board,kind):
    engine,_,clock=world;engine.config.inspect_hand_cards=True;engine.config.auto_sell_for_space=enabled
    t=dict(targets,hand_1=(.45,.9),friendly_target=(.28,.54),tavernkeeper=(.5,.19))
    obs=Observation(State.RECRUIT,.99,True,t,metrics={'gold':2,'hand_count':1},board_count=board,hand_minions=['hand_1'])
    settle(engine,clock,obs)
    engine.hand_probe={'point':(.45,.9),'count':1,'stage':'ready','kind':kind,'source':'hand'}
    action=engine.decide(obs)
    assert action is None or action.target!='sell_minion'


def test_full_board_can_sell_to_fund_a_verified_shop_minion(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True;engine.config.auto_sell_for_space=True
    t=dict(targets,friendly_target=(.28,.54),tavernkeeper=(.5,.19))
    obs=Observation(State.RECRUIT,.99,True,t,metrics={'gold':2,'hand_count':0},board_count=7,shop_minions=['shop_1'])
    settle(engine,clock,obs)
    sale=engine.decide(obs);assert sale.target=='sell_minion'
    engine.sent(sale,obs)
    after=Observation(State.RECRUIT,.99,True,t,metrics={'gold':3,'hand_count':0},board_count=6,shop_minions=['shop_1'])
    settle(engine,clock,after)
    buy=engine.decide(after)
    assert buy.target=='shop_1' and buy.destination=='hand_drop'


def test_random_tavern_theft_uses_no_target_and_verifies_replacement_card(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    t=dict(targets,hand_1=(.45,.9))
    obs=Observation(State.RECRUIT,.99,True,t,metrics={'gold':0,'hand_count':1,'shop_card_count':4},board_count=7,hand_minions=['hand_1'])
    settle(engine,clock,obs)
    engine.hand_probe={'point':(.45,.9),'count':1,'stage':'ready','kind':'steal','source':'hand'}
    use=engine.decide(obs)
    assert use.target=='inspected_hand' and use.destination=='board_drop'
    engine.sent(use,obs)
    after=Observation(State.RECRUIT,.99,True,t,metrics={'gold':0,'hand_count':1,'shop_card_count':4},board_count=7,hand_minions=['hand_1'])
    settle(engine,clock,after)
    assert not engine.feedback(use,obs,after)
    after.metrics['shop_card_count']=3;settle(engine,clock,after)
    assert engine.feedback(use,obs,after)


def test_arrow_without_choice_context_never_authorizes_friendly_click(world,targets):
    engine,_,clock=world
    obs=Observation(State.RECRUIT,.99,True,targets,metrics={'targeting_arrow':1,'gold':10},
                    board_count=2,hand_minions=['hand_1'],shop_minions=['shop_1'])
    settle(engine,clock,obs)
    assert engine.decide(obs).target!='friendly_target'


def test_trinket_selection_needs_confirm(world,targets):
    engine,_,clock=world
    obs=Observation(State.CHOICE,.99,True,dict(targets,choice_confirm=(.5,.7)),
                    metrics={'choice_confirm_ready':0})
    settle(engine,clock,obs)
    assert engine.decide(obs).target=='choice_1'
    obs.metrics['choice_confirm_ready']=1
    settle(engine,clock,obs)
    assert engine.decide(obs).target=='choice_confirm'


def test_only_actual_available_middle_hero(world,targets):
    engine,store,clock=world
    obs=Observation(State.HERO,.99,True,targets,available_heroes=[1,3,4])
    settle(engine,clock,obs)
    action=engine.decide(obs)
    assert action.target=='hero_3'
    engine.sent(action,obs)
    assert store.recent()[0]['hero_slot']==3


def test_locked_middle_heroes_never_clicked(world,targets):
    engine,_,clock=world
    obs=Observation(State.HERO,.99,True,targets,available_heroes=[1,4])
    settle(engine,clock,obs)
    assert engine.decide(obs) is None
    clock.advance(16)
    with pytest.raises(NeedsAttention,match='可选状态'):engine.decide(obs)


def test_hero_confirmation_requires_selected_feedback(world,targets):
    engine,_,clock=world
    obs=Observation(State.HERO,.99,True,targets,available_heroes=[2,3])
    settle(engine,clock,obs)
    action=engine.decide(obs);engine.sent(action,obs)
    clock.advance(2)
    assert engine.decide(obs) is None
    selected=Observation(State.HERO,.99,True,targets,metrics={'hero_selected_slot':2},available_heroes=[2,3])
    settle(engine,clock,selected)
    assert engine.decide(selected).target=='hero_confirm'


def test_ocr_hint_cannot_authorize_input(world,targets):
    engine,_,clock=world
    obs=Observation(State.LOBBY,.6,False,targets)
    settle(engine,clock,obs,4)
    assert engine.decide(obs) is None


def test_combat_never_buys_or_plays(world,targets):
    engine,_,clock=world
    obs=Observation(State.COMBAT,.99,True,targets,metrics={'gold':10,'upgrade_cost':1,'tavern_tier':1},
                    hand_minions=['hand_1'],shop_minions=['shop_1'],board_count=0)
    settle(engine,clock,obs,4)
    assert engine.decide(obs) is None


def test_authentication_requests_handoff(world,targets):
    engine,_,clock=world
    obs=Observation(State.AUTH,.99,False,targets)
    settle(engine,clock,obs)
    with pytest.raises(NeedsAttention,match='认证'):engine.decide(obs)


def test_unknown_gold_blocks_purchase(world,targets):
    engine,_,clock=world
    obs=Observation(State.RECRUIT,.99,True,targets,shop_minions=['shop_1'],board_count=0)
    settle(engine,clock,obs)
    assert engine.decide(obs) is None


def test_unrelated_ocr_change_does_not_confirm_a_purchase(world,targets):
    engine,_,clock=world
    obs=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':6,'upgrade_cost':5},shop_minions=['shop_1'],board_count=0)
    settle(engine,clock,obs)
    buy=engine.decide(obs);engine.sent(buy,obs)
    changed=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':6,'upgrade_cost':4},shop_minions=['shop_1'],board_count=0)
    settle(engine,clock,changed)
    assert engine.decide(changed) is None


def test_full_board_blocks_minion_play_and_purchase(world,targets):
    engine,_,clock=world
    obs=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':10},shop_minions=['shop_1'],hand_minions=['hand_1'],board_count=7)
    settle(engine,clock,obs)
    assert engine.decide(obs) is None


def test_upgrade_requires_known_tier_and_cost_and_reserve(world,targets):
    engine,_,clock=world
    unknown=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':10,'upgrade_cost':4},board_count=0)
    settle(engine,clock,unknown)
    assert engine.decide(unknown) is None
    known=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':8,'upgrade_cost':4,'tavern_tier':2},board_count=0)
    settle(engine,clock,known)
    assert engine.decide(known).target=='upgrade'
    poor=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':6,'upgrade_cost':4,'tavern_tier':2},board_count=0)
    settle(engine,clock,poor)
    assert engine.decide(poor) is None


@pytest.mark.parametrize('tier,cost,gold',[(4,11,14),(5,13,16)])
@pytest.mark.parametrize('board',[7,None])
def test_high_tier_upgrade_ignores_board_capacity_but_checks_economy(world,targets,tier,cost,gold,board):
    engine,_,clock=world
    obs=Observation(State.RECRUIT,.99,True,targets,
                    metrics={'gold':gold,'upgrade_cost':cost,'tavern_tier':tier},
                    hand_minions=['hand_1'],board_count=board)
    settle(engine,clock,obs)
    action=engine.decide(obs)
    assert action.target=='upgrade'
    engine.sent(action,obs)
    after=Observation(State.RECRUIT,.99,True,targets,metrics={'tavern_tier':tier+1})
    assert engine.feedback(action,obs,after)


def test_tier_six_never_upgrades(world,targets):
    engine,_,clock=world
    obs=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':30,'upgrade_cost':0,'tavern_tier':6},board_count=7)
    settle(engine,clock,obs)
    assert engine.decide(obs) is None


def test_full_board_uses_reserve_for_tier_six_before_inspecting_hand(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    obs=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':10,'upgrade_cost':10,'tavern_tier':5},
                    board_count=7,hand_minions=['hand_1'])
    settle(engine,clock,obs)
    assert engine.decide(obs).target=='upgrade'


@pytest.mark.parametrize('cost',[0,2])
def test_shop_spell_purchase_requires_buff_description_and_cost(world,targets,cost):
    engine,_,clock=world;engine.config.inspect_hand_cards=True;engine.config.test_shop_spells=True
    t=dict(targets,spell_shop_5=(.65,.37))
    obs=Observation(State.RECRUIT,.99,True,t,metrics={'gold':4,'spell_shop_5_cost':cost,'hand_count':0},board_count=4,shop_spells=['spell_shop_5'])
    settle(engine,clock,obs)
    hover=engine.decide(obs);assert hover.kind=='hover' and hover.target=='spell_shop_5'
    engine.sent(hover,obs);obs.metrics['hand_card_kind']='buff'
    settle(engine,clock,obs)
    clear=engine.decide(obs);engine.sent(clear,obs)
    settle(engine,clock,obs)
    buy=engine.decide(obs)
    assert buy.target=='inspected_shop_spell' and buy.destination=='hand_drop'
    assert not engine.feedback(buy,obs,obs)
    after=Observation(State.RECRUIT,.99,True,t,metrics={'gold':4-cost,'hand_count':1},board_count=4)
    settle(engine,clock,after)
    assert engine.feedback(buy,obs,after)


def test_own_tooltip_hiding_anchor_only_authorizes_mouse_move(world,targets):
    engine,_,clock=world
    engine.hand_probe={'point':(.65,.37),'stage':'inspect','since':clock(),'source':'shop','count':0}
    obs=Observation(State.UNKNOWN,.0,False,metrics={'hand_card_kind':'buff'})
    settle(engine,clock,obs)
    action=engine.decide(obs)
    assert action.kind=='hover' and action.target=='clear_tooltip'
    engine.sent(action,obs)
    assert engine.hand_probe['kind']=='buff'
    clock.advance(1)
    assert engine.decide(obs) is None


def test_target_prompt_blocks_shopping_and_selects_verified_friendly(world,targets):
    engine,_,clock=world
    obs=Observation(State.RECRUIT,.99,True,dict(targets,friendly_target=(.5,.55)),
                    metrics={'gold':10,'targeting_arrow':1,'friendly_target_verified':1},
                    shop_minions=['shop_1'],board_count=None,evidence='选择一个友方随从')
    settle(engine,clock,obs)
    a=engine.decide(obs)
    assert a.kind=='click' and a.target=='friendly_target'
    engine.sent(a,obs);clock.advance(1)
    assert engine.decide(obs) is None


def test_stop_preserves_incomplete_match(world,targets):
    engine,store,clock=world
    settle(engine,clock,Observation(State.RECRUIT,.99,True,targets))
    engine.interrupt()
    record=store.recent()[0]
    assert record['result_status']=='interrupted'
    assert record['rating_delta'] is None
    assert engine.completed==0


def test_pause_resume_forgets_old_numeric_evidence(world,targets):
    engine,_,clock=world
    obs=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':10})
    settle(engine,clock,obs)
    assert engine.confirmed_metrics['gold']==10
    engine.reset_observation()
    assert engine.confirmed_metrics=={}
    assert engine.decide(obs) is None


def test_test_concede_is_recorded_only_after_concede_click(world,targets):
    engine,store,clock=world
    engine.config.test_concede=True;engine.config.concede_after_seconds=5
    recruit=Observation(State.RECRUIT,.99,True,targets)
    settle(engine,clock,recruit)
    clock.advance(6)
    esc=engine.decide(recruit)
    assert esc.kind=='key' and esc.key=='Escape'
    engine.sent(esc,recruit)
    assert store.recent()[0]['end_reason']=='normal'
    menu=Observation(State.MENU,.99,True,targets)
    settle(engine,clock,menu)
    click=engine.decide(menu);engine.sent(click,menu)
    assert store.recent()[0]['end_reason']=='test_concede'
    confirm=Observation(State.CONFIRM,.99,True,targets)
    settle(engine,clock,confirm)
    assert engine.decide(confirm).target=='confirm_concede'


def test_two_matches_result_deduplication_and_restart(world,targets):
    engine,store,clock=world
    engine.config.max_matches=2
    for index in range(2):
        before=6000-index*100
        lobby=Observation(State.LOBBY,.99,True,targets,metrics={'rating':before})
        settle(engine,clock,lobby,4)
        play=engine.decide(lobby);assert play.target=='lobby_play';engine.sent(play,lobby)
        queue=Observation(State.QUEUE,.99,True,targets)
        settle(engine,clock,queue);assert engine.decide(queue) is None
        hero=Observation(State.HERO,.99,True,targets,available_heroes=[2,3])
        settle(engine,clock,hero)
        choose=engine.decide(hero);engine.sent(choose,hero)
        recruit=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':3},shop_minions=['shop_1'],board_count=0)
        settle(engine,clock,recruit)
        buy=engine.decide(recruit);assert buy.target=='shop_1';engine.sent(buy,recruit)
        after=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':0},hand_minions=['hand_1'],board_count=0)
        settle(engine,clock,after)
        use=engine.decide(after);assert use.target=='hand_1';engine.sent(use,after)
        combat=Observation(State.COMBAT,.99,True,targets)
        settle(engine,clock,combat)
        result=Observation(State.RESULT,.99,True,targets,metrics={'placement':8,'rating':before-100})
        settle(engine,clock,result,8)
        leave=engine.decide(result);assert leave.target=='result_continue';engine.sent(leave,result)
        assert len(store.recent())==index+1
        end=Observation(State.LOBBY,.99,True,targets,metrics={'rating':before-100})
        settle(engine,clock,end,5)
        assert engine.completed==index+1
        clock.advance(3)
    assert engine.done
    assert engine.decide(end) is None
    assert len(store.recent())==2
    assert all(r['rating_delta']==-100 for r in store.recent())


def test_result_ocr_failure_remains_null(world,targets):
    engine,store,clock=world
    settle(engine,clock,Observation(State.HERO,.99,True,targets,available_heroes=[2]))
    result=Observation(State.RESULT,.99,True,targets)
    settle(engine,clock,result,8)
    assert engine.decide(result).target=='result_continue'
    settle(engine,clock,Observation(State.LOBBY,.99,True,targets),7)
    record=store.recent()[0]
    assert record['placement'] is None and record['rating_after'] is None
    assert record['result_status']=='partial'


def test_unexpected_return_to_lobby_stops_auto_restart(world,targets):
    engine,_,clock=world
    settle(engine,clock,Observation(State.RECRUIT,.99,True,targets))
    with pytest.raises(NeedsAttention,match='未观察到结算'):
        settle(engine,clock,Observation(State.LOBBY,.99,True,targets),3)
