#!/usr/bin/env python3

""" Main entry Point for prod agent."""


from agent.agent import Agent
from agent.observability.telemetry import setup_telemetry, shutdown_telemetry
from agent.types.types import SecurityContext


def banner():
    print("*** Starting prod agent! ***")


def run_demo(agent: Agent, ctx: SecurityContext, prompt: str, label:str):
    try:
        resp= agent.run(prompt, ctx, label=label)
        print(f"[{label}] Response : {resp.content}")
        print(f"[{label}] Timings  : {resp.layer_timings}")
        print(f"[{label}] Cost     : ${resp.cost_usd}")
        print(f"[{label}] Tokens   : {resp.tokens_used}")
    except PermissionError as e:
        print(f"[{label}] BLOCKED  : {e}")
    except ValueError as e:
        print(f"[{label}] REJECTED : {e}")    



def main():
    setup_telemetry()
    agent = Agent()
    ctx_guest = SecurityContext(
        user_id="demo-user",
        session_id="session_demo",
        permissions=["read"],
        rate_limit_tier="standard",
    )
    run_demo(agent, ctx_guest, "Explain the 4-layer agent architecture.", "NORMAL")
    shutdown_telemetry()



if __name__ == "__main__":
    main()