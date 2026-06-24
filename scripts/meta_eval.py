"""
=============================================================================
ThirdLine — Meta-Evaluation Script
=============================================================================

FILE: scripts/meta_eval.py

WHAT THIS FILE DOES:
    Computes ThirdLine's OWN detection performance against the known
    ground truth labels in ground_truth.json.

    This is the single most important metric in the project:
      - Precision: of findings raised, what % caught a real defect?
      - Recall:    of all injected defects, what % did ThirdLine catch?
      - F1:        harmonic mean of precision and recall

    Run this AFTER scripts/run_audit.py has completed.

OUTPUT:
    Prints a full performance report to the terminal.
    Saves data/evaluations/meta_eval_results.json
=============================================================================
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from config.settings import settings
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def load_ground_truth() -> dict:
    gt_path = Path("agents_under_audit/data/ground_truth.json")
    return json.loads(gt_path.read_text())


def load_findings() -> list[dict]:
    findings = []
    findings_dir = settings.data_dir / "findings"
    for f in findings_dir.glob("run_*.json"):
        data = json.loads(f.read_text())
        findings.extend(data.get("findings", []))
    return findings


def compute_metrics(gt: dict, findings: list[dict]) -> dict:
    """
    Compute per-agent and overall detection metrics.

    For point-defect agents (hallucination, robustness, reliability):
      TP = ThirdLine raised a finding AND the defect was injected
      FP = ThirdLine raised a finding BUT no defect was injected
      FN = defect was injected BUT ThirdLine missed it

    For population-defect agents (bias, drift):
      TP = ThirdLine raised a finding for the affected agent
      FN = no finding raised for the affected agent
    """
    # Which agents had defects injected?
    agents_with_defects = {
        agent_id: data["primary_defect"]
        for agent_id, data in gt["agents"].items()
    }

    # Which agents got findings from ThirdLine?
    agents_with_findings = {}
    for f in findings:
        aid = f["agent_id"]
        dim = f["dimension"]
        if aid not in agents_with_findings:
            agents_with_findings[aid] = []
        agents_with_findings[aid].append(dim)

    results = []
    for agent_id, defect_type in agents_with_defects.items():
        agent_findings_dims = agents_with_findings.get(agent_id, [])
        detected = defect_type in agent_findings_dims

        results.append({
            "agent_id": agent_id,
            "expected_defect": defect_type,
            "finding_dimensions": agent_findings_dims,
            "detected": detected,
            "tp": 1 if detected else 0,
            "fn": 0 if detected else 1,
        })

    # FP: findings for dimensions where no defect was injected
    fp_count = 0
    for agent_id, finding_dims in agents_with_findings.items():
        expected_defect = agents_with_defects.get(agent_id, "")
        for dim in finding_dims:
            if dim != expected_defect:
                fp_count += 1

    tp = sum(r["tp"] for r in results)
    fn = sum(r["fn"] for r in results)
    fp = fp_count

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "per_agent": results,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "agents_evaluated": len(results),
        "agents_detected": tp,
    }


def main():
    console.print("\n[bold blue]ThirdLine — Meta-Evaluation[/bold blue]\n")

    gt = load_ground_truth()
    findings = load_findings()

    if not findings:
        console.print("[red]No findings found. Run scripts/run_audit.py first.[/red]")
        return

    metrics = compute_metrics(gt, findings)

    # Per-agent table
    table = Table(title="Per-Agent Detection Results", border_style="blue")
    table.add_column("Agent", style="cyan")
    table.add_column("Expected Defect", style="yellow")
    table.add_column("Dimensions Found")
    table.add_column("Detected?", justify="center")

    for r in metrics["per_agent"]:
        detected = r["detected"]
        table.add_row(
            r["agent_id"].replace("agt-", "").replace("-001", ""),
            r["expected_defect"],
            ", ".join(r["finding_dimensions"]) or "none",
            "[green]✓ TP[/green]" if detected else "[red]✗ FN[/red]",
        )
    console.print(table)

    # Aggregate metrics
    console.print(Panel.fit(
        f"[bold]ThirdLine Detection Performance[/bold]\n\n"
        f"  True Positives:   {metrics['tp']}\n"
        f"  False Positives:  {metrics['fp']}\n"
        f"  False Negatives:  {metrics['fn']}\n\n"
        f"  [bold green]Precision: {metrics['precision']:.1%}[/bold green]\n"
        f"  [bold green]Recall:    {metrics['recall']:.1%}[/bold green]\n"
        f"  [bold green]F1 Score:  {metrics['f1']:.3f}[/bold green]\n\n"
        f"  Agents evaluated: {metrics['agents_evaluated']}\n"
        f"  Defects detected: {metrics['agents_detected']} / {metrics['agents_evaluated']}",
        border_style="green"
    ))

    # Save results
    out_path = settings.data_dir / "evaluations" / "meta_eval_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, indent=2, default=str))
    console.print(f"\n[dim]Results saved to {out_path}[/dim]")
    console.print("\n[bold]These are the metrics that go in your resume bullet and README.[/bold]")


if __name__ == "__main__":
    main()
