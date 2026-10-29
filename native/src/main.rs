use std::io::{self, BufRead, Write};
use penta::{Game, GameResult, HandcraftedPolicy, PlayerId, Policy};
use penta::protocol::{self, action_json, deck_by_name_for_format, observation_json_for_format, protocol_actions};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

fn emit(value: Value) {
    println!("{value}");
    io::stdout().flush().expect("flush benchmark protocol");
}
fn read(lines: &mut impl Iterator<Item=io::Result<String>>) -> Result<Value,String> {
    serde_json::from_str(&lines.next().ok_or("command stream closed")?.map_err(|e|e.to_string())?).map_err(|e|e.to_string())
}
struct Uniform(u64);
impl Uniform {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e3779b97f4a7c15);
        let mut x = self.0;
        x = (x ^ (x >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        x = (x ^ (x >> 27)).wrapping_mul(0x94d049bb133111eb);
        x ^ (x >> 31)
    }
    fn choose(&mut self, n: usize) -> usize {
        let n = n as u64;
        let threshold = n.wrapping_neg() % n;
        loop { let x=self.next(); if x>=threshold { return (x%n) as usize; } }
    }
}
fn run(config: Value, lines: &mut impl Iterator<Item=io::Result<String>>) -> Result<(),String> {
    let format=protocol::parse_format_slug(config["format"].as_str().ok_or("missing format")?)?;
    let names=config["decks"].as_array().ok_or("missing decks")?;
    let agents=config["agents"].as_array().ok_or("missing agents")?;
    if names.len()!=2 || agents.len()!=2 { return Err("exactly two seats required".into()); }
    let deck = |i:usize| deck_by_name_for_format(format,names[i].as_str().unwrap_or("")).ok_or("unknown deck".to_string());
    let catalog=penta::poc::catalog().map_err(|e|e.to_string())?;
    let seed=config["seed"].as_u64().ok_or("missing seed")?;
    let mut game=Game::new_with_format(format,catalog.clone(),[deck(0)?,deck(1)?],seed).map_err(|e|e.to_string())?;
    let mut handcrafted=[HandcraftedPolicy::new(catalog.clone()), HandcraftedPolicy::new(catalog.clone())];
    let mut random=[Uniform(config["policySeeds"][0].as_u64().ok_or("missing policy seed")?),Uniform(config["policySeeds"][1].as_u64().ok_or("missing policy seed")?)];
    let replay=config["replay"].as_array().cloned().unwrap_or_default();
    let mut position=0usize;
    emit(json!({"type":"start","fingerprint":protocol::SIMULATION_FINGERPRINT,"protocol":protocol::PROTOCOL_VERSION,"engineVersion":protocol::ENGINE_VERSION}));
    let limit=config["maxActions"].as_u64().unwrap_or(100000) as usize;
    while game.result().is_none() && position<limit {
        let seat=game.decision_player().ok_or("live game without decision")?;
        let i=seat.index();
        let seat_name=if i==0 {"p1"} else {"p2"};
        let mut observation=game.observe_state(seat);
        observation.legal_actions=game.legal_actions(seat);
        let actions=protocol_actions(&observation);
        if actions.is_empty() { return Err("live game without legal action".into()); }
        let mut view=observation_json_for_format(&catalog,format,&observation,game.in_pregame(),&actions);
        view["match"]=game.match_json(seat);
        let hash=Sha256::digest(view.to_string().as_bytes()).iter().map(|b|format!("{b:02x}")).collect::<String>();
        let agent=agents[i].as_str().ok_or("invalid agent")?;
        let (action,index,source)=if actions.len()==1 {
            (actions[0].clone(),Some(0),"forced")
        } else if agent=="handcrafted" {
            let chosen=handcrafted[i].choose_action(&observation).ok_or("handcrafted returned no action")?;
            let index=actions.iter().position(|a|*a==chosen);
            (chosen,index,"handcrafted")
        } else if agent=="random" {
            let index=random[i].choose(actions.len());
            (actions[index].clone(),Some(index),"random")
        } else if agent=="luna" {
            let answer=if position<replay.len() { replay[position].clone() } else {
                emit(json!({"type":"observe","seat":seat_name,"observation":view,"position":position}));
                read(lines)?
            };
            let index=answer["index"].as_u64().ok_or("missing action index")? as usize;
            (actions.get(index).ok_or("action index out of range")?.clone(),Some(index),"luna")
        } else { return Err("unknown agent".into()); };
        let entry=json!({"type":"action","seat":seat_name,"position":position,"index":index,"action":action_json(&action),"observationHash":hash,"source":source});
        if position<replay.len() && entry!=replay[position] { return Err(format!("replay mismatch at action {position}")); }
        game.apply(seat,action).map_err(|e|e.to_string())?;
        if position>=replay.len() { emit(entry); }
        position+=1;
    }
    if position<replay.len() { return Err("journal extends beyond game".into()); }
    let result=match game.result() { Some(GameResult::Draw)=>Some("draw"),Some(GameResult::Winner{winner,..})=>Some(if winner==PlayerId::One {"p1"}else{"p2"}),None=>None };
    emit(json!({"type":"result","result":result,"status":if result.is_some(){"complete"}else{"truncated"},"decisions":position}));
    Ok(())
}
fn main() {
    let stdin=io::stdin();
    let mut lines=stdin.lock().lines();
    while let Some(line)=lines.next() {
        let result=line.map_err(|e|e.to_string()).and_then(|s|serde_json::from_str(&s).map_err(|e|e.to_string())).and_then(|config|run(config,&mut lines));
        if let Err(error)=result {emit(json!({"type":"error","error":error})); break;}
    }
}
