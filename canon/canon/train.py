"""train — LoRA fine-tune of a small open model on verified cite-only trajectories.

Default base: microsoft/bitnet-b1.58-2B-4T-bf16 — the bf16 master weights of Microsoft's 1.58-bit (ternary)
2B model. Fine-tune on the bf16 master, then re-quantise to ternary for serving with bitnet.cpp (CPU, no GPU,
offline). The canon never enters the weights; the model learns one skill — look up, then cite — which is
exactly the skill a ternary model can hold. Fallbacks that train identically: Qwen/Qwen2.5-1.5B-Instruct,
HuggingFaceTB/SmolLM2-1.7B-Instruct, meta-llama/Llama-3.2-1B-Instruct.

    python -m canon.train --data data/train.jsonl --out runs/canon-bitnet \\
        [--base microsoft/bitnet-b1.58-2B-4T-bf16] [--epochs 2] [--lr 2e-4] [--r 16]

Needs a GPU box with `pip install "canon[train]"`. This file only prepares and launches the run; the data
it trains on has already passed the hash filter (synth.check_example) — nothing unverified is ever seen.
Loss is on assistant tokens only (tool calls and final answers), never on tool results or the user turn.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_BASE = "microsoft/bitnet-b1.58-2B-4T-bf16"
FALLBACKS = ["Qwen/Qwen2.5-1.5B-Instruct", "HuggingFaceTB/SmolLM2-1.7B-Instruct", "meta-llama/Llama-3.2-1B-Instruct"]


def load_rows(path: Path) -> List[Dict[str, Any]]:
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    bad = [i for i, r in enumerate(rows) if "messages" not in r or not r.get("checked")]
    if bad:
        raise SystemExit(f"{len(bad)} rows lack the `checked` stamp from synth.check_example — refusing to train on unverified data")
    return rows


def _to_text(tokenizer, ex: Dict[str, Any]) -> str:
    """Render one trajectory with the model's own chat template (tool calls included where the template
    supports them; otherwise tool turns are rendered as plain role blocks)."""
    try:
        return tokenizer.apply_chat_template(ex["messages"], tools=ex.get("tools"), tokenize=False)
    except Exception:  # noqa: BLE001 — templates without tool support
        parts = []
        for m in ex["messages"]:
            c = m.get("content")
            if m.get("tool_calls"):
                c = "<tool_call>" + json.dumps(m["tool_calls"][0]["function"]) + "</tool_call>"
            parts.append(f"<|{m['role']}|>\n{c}\n")
        return "".join(parts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--eval", help="held-out jsonl (default: last 5% of --data)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default=os.environ.get("CANON_BASE", DEFAULT_BASE))
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--r", type=int, default=16, help="LoRA rank")
    ap.add_argument("--max-len", type=int, default=2048)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true", help="render and count tokens; no model download, no training")
    a = ap.parse_args(argv)

    rows = load_rows(Path(a.data))
    if a.eval:
        ev = load_rows(Path(a.eval))
    else:
        k = max(1, len(rows) // 20)
        rows, ev = rows[:-k], rows[-k:]
    print(f"train {len(rows)} / eval {len(ev)} verified trajectories; base {a.base}")
    if a.dry_run:
        fams: Dict[str, int] = {}
        for r in rows:
            fams[r["family"]] = fams.get(r["family"], 0) + 1
        print("families:", fams)
        print("sample:", json.dumps(rows[0]["messages"][1:], ensure_ascii=False)[:400])
        return 0

    import torch  # noqa: F401  (import errors here mean: pip install "canon[train]")
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    tok = AutoTokenizer.from_pretrained(a.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(a.base, torch_dtype="auto", device_map="auto")
    ds = Dataset.from_list([{"text": _to_text(tok, r)} for r in rows])
    ds_ev = Dataset.from_list([{"text": _to_text(tok, r)} for r in ev])
    lora = LoraConfig(r=a.r, lora_alpha=2 * a.r, lora_dropout=0.05, task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    cfg = SFTConfig(output_dir=a.out, num_train_epochs=a.epochs, learning_rate=a.lr, per_device_train_batch_size=a.batch,
                    gradient_accumulation_steps=max(1, 16 // a.batch), max_length=a.max_len, logging_steps=10,
                    eval_strategy="epoch", save_strategy="epoch", bf16=True, report_to=[],
                    assistant_only_loss=True, packing=False)
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds, eval_dataset=ds_ev, processing_class=tok, peft_config=lora)
    trainer.train()
    trainer.save_model(a.out)
    (Path(a.out) / "CANON.json").write_text(json.dumps({"base": a.base, "train_rows": len(rows), "eval_rows": len(ev),
                                                        "lora_r": a.r, "epochs": a.epochs,
                                                        "note": "data passed synth.check_example before training; "
                                                                "evaluate with canon.evaluate against the canon"}, indent=1))
    print("saved", a.out, "— next: python -m canon.evaluate --model", a.out)
    if "bitnet" in a.base.lower():
        print("ternary serving: merge the adapter into the bf16 master, then convert with bitnet.cpp's setup_env / "
              "convert script to an i2_s GGUF; serve with `bitnet.cpp run`. The canon tools stay outside the model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
