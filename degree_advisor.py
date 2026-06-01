"""Degree Advisor — compare time-to-graduation across degree scenarios.

You start with the one major you're declared as (your baseline) and paste its
CU Boulder DegreeWorks audit. Then you stack up comparisons in a single run:
add a minor, add a second major, switch majors, etc. For each one you paste
that program's own standalone audit.

Each audit already has your completed courses applied to it, and states how many
more credits that program still needs (its "NEEDS: X HOURS" line). The app reads
those numbers and combines them:

    credits remaining for a scenario =
        max( 120 - your completed credits,            # the graduation floor
             sum of each program's still-needed credits )

So adding a major whose requirements push the total past 120 is detected
automatically. Credits remaining are then converted to semesters (rounded up)
and years, and each scenario is compared against your baseline.

Shared requirements (writing, gen-ed, etc.) are never double-counted: the
per-program "needs" are major-department credits only, and anything shared is
counted once via the 120 floor (it's either already in your completed credits
or part of "120 - completed"). At the confirm step you can raise a program's
number to include its required NON-department courses (e.g. CS logic/ethics).

Umbrella/container requirements ("45 upper-division hours", "30 upper-div in
A&S") are NOT charged separately: they demand no new courses, just that some of
what you take qualifies, and the major coursework (e.g. upper-division CSCI
classes also satisfying Econ's upper-division rule) fills them for free. Caveat:
the floor enforces the 120 total, not such sub-rules, so a plan with enough
total credits but too few upper-division ones would not be flagged.

Assumptions (shown in the output so you can sanity-check): in-progress credits
count as completed; a major's "additional area of study" requirement is covered
by the minor / second major in the scenario (or by existing coursework).

Standard library only.
"""

import math
import re

DEGREE_MINIMUM = 120  # CU Boulder baccalaureate minimum credit hours


# --------------------------------------------------------------------------- #
# Input helpers
# --------------------------------------------------------------------------- #

def ask_number(prompt, default=None, minimum=0.0, integer=False):
    """Prompt until a valid number >= minimum. Blank takes the default if given."""
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if raw == "" and default is not None:
            return default
        try:
            value = int(raw) if integer else float(raw)
        except ValueError:
            print("  Please enter a number.")
            continue
        if value < minimum:
            print(f"  Please enter at least {minimum:g}.")
            continue
        return value


def ask_yes_no(prompt, default=True):
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{hint}]: ").strip().lower()
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please answer y or n.")


def ask_text(prompt, default=None):
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw or (default or "")


def fmt(n):
    """Trim trailing .0 so 4.0 -> 4 but 4.5 stays 4.5."""
    return f"{n:g}"


def money(n):
    """Format a dollar amount: 40000 -> $40,000."""
    return f"${n:,.0f}"


# --------------------------------------------------------------------------- #
# Audit reading / parsing
# --------------------------------------------------------------------------- #

def read_pasted_audit():
    """Read pasted audit text until a line containing only END (or EOF)."""
    print("  Paste the audit below, then press Enter and type END (or Ctrl+Z):")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip().upper() == "END":
            break
        lines.append(line)
    return "\n".join(lines)


def _find_float(pattern, text, flags=re.IGNORECASE):
    m = re.search(pattern, text, flags)
    return float(m.group(1)) if m else None


def extract_completed(text):
    """Pull (earned, in_progress) total cumulative credits from an audit."""
    earned = _find_float(r"EARNED:?\s*([\d.]+)\s*HOURS", text)
    in_prog = _find_float(r"IN[\s-]*PROGRESS:?\s*([\d.]+)\s*HOURS", text)
    return earned, in_prog


def extract_program_need(text):
    """Find a program's main 'at least N hours of DEPT' requirement and the
    credits it still needs. Returns (dept, still_needed) or (None, None)."""
    # The primary major/minor hours requirement is the one with the largest N
    # (e.g. "at least 45 hours of approved CSCI", "at least 32 hours of ECON").
    # DEPT must be an uppercase prefix, so phrases like "of upper-division ECON"
    # or "of the required 45" don't match.
    best = None  # (required_n, dept, end_index)
    for m in re.finditer(
        r"at least\s+(\d+)\s+hours of\s+(?:approved\s+)?([A-Z]{2,4})", text
    ):
        n = int(m.group(1))
        if best is None or n > best[0]:
            best = (n, m.group(2).upper(), m.end())
    if best is None:
        return None, None

    # The NEEDS for this requirement is the first one after it, bounded by the
    # start of the next top-level Requirement block.
    tail = text[best[2]:]
    bound = re.search(r"\nRequirement:", tail)
    if bound:
        tail = tail[: bound.start()]
    need = _find_float(r"NEEDS:?\s*([\d.]+)\s*HOURS", tail)
    return best[1], (need if need is not None else 0.0)


def confirm_or_ask(value, label, default=None):
    """Confirm a parsed value, or prompt for it if missing / rejected."""
    if value is not None:
        print(f"  Found {label}: {fmt(value)} hours")
        if ask_yes_no(f"  Use {label} = {fmt(value)}?", default=True):
            return value
    return ask_number(f"  {label.capitalize()}", default=default, minimum=0)


def ask_program_need(dept, need, label):
    """Confirm a program's still-needed credits, allowing the total to be raised
    to include required courses outside the major department (e.g. logic/ethics).
    Shared gen-ed should NOT be added here - it's counted once via the floor."""
    if dept is None:
        return ask_number(f"  Credits {label} still needs", minimum=0)
    print(f"  Found: {label} still needs {fmt(need)} more {dept} (major) credits.")
    print(f"  Add any required NON-{dept} courses it still needs (e.g. logic, "
          f"ethics); skip shared gen-ed - that's counted once already.")
    return ask_number("  Total credits this program still needs",
                      default=need, minimum=0)


def collect_program_need(program_label):
    """Paste one program's audit and return how many credits it still needs."""
    print(f"  Paste the audit for: {program_label}")
    text = read_pasted_audit()
    dept, need = extract_program_need(text)
    return ask_program_need(dept, need, program_label)


# --------------------------------------------------------------------------- #
# Scenario building
# --------------------------------------------------------------------------- #

# (label, programs added beyond baseline, whether baseline major is kept)
COMPARISON_OPTIONS = [
    ("Add a minor", 1, True),
    ("Add a second major", 1, True),
    ("Switch to a different major", 1, False),
    ("Add two minors", 2, True),
    ("Add a second major and a minor", 2, True),
    ("Something else (custom)", None, True),
]


def choose_comparison():
    """Show the menu; return (label, n_programs, keep_baseline) or None to finish."""
    print("\nWhat do you want to compare?")
    for i, (name, _, _) in enumerate(COMPARISON_OPTIONS, 1):
        print(f"  {i}) {name}")
    done = len(COMPARISON_OPTIONS) + 1
    print(f"  {done}) Done - show me the comparison")

    choice = int(ask_number("Choose", default=done, minimum=1, integer=True))
    if choice >= done or choice < 1:
        return None
    name, n_programs, keep_baseline = COMPARISON_OPTIONS[choice - 1]
    label = ask_text("  Name this scenario", default=name)
    if n_programs is None:  # custom
        n_programs = int(ask_number("  How many programs does it add?",
                                    default=1, minimum=1, integer=True))
        keep_baseline = ask_yes_no("  Keep your current major in this scenario?",
                                   default=True)
    return label, n_programs, keep_baseline


def remaining_for(needs, floor):
    """Credits remaining = max(graduation floor, sum of program-specific needs)."""
    specific = sum(needs)
    remaining = max(floor, specific)
    driver = "120-credit minimum" if floor >= specific else "major requirements"
    return remaining, driver


def print_results(scenarios, cps, spy, cost_per_sem):
    base = scenarios[0]
    base_sem = math.ceil(base["remaining"] / cps)
    base_cost = base_sem * cost_per_sem

    rows = []
    for s in scenarios:
        semesters = math.ceil(s["remaining"] / cps)
        years = semesters / spy
        cost = semesters * cost_per_sem
        delta = ("baseline" if s is base else
                 f"+{semesters - base_sem} sem, +{money(cost - base_cost)}")
        rows.append((s["label"], fmt(s["remaining"]), str(semesters),
                     fmt(years), money(cost), s["driver"], delta))

    headers = ("Scenario", "Cr left", "Sem", "Years", "Cost",
               "Driven by", "vs. baseline")
    widths = [max(len(headers[i]), max(len(r[i]) for r in rows))
              for i in range(len(headers))]

    def line(cols):
        return "  ".join(c.ljust(widths[i]) for i, c in enumerate(cols))

    print("\n=== Comparison ===")
    print(line(headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(line(row))


# --------------------------------------------------------------------------- #
# Main flow
# --------------------------------------------------------------------------- #

def main():
    print("=== Degree Advisor ===")
    print(f"Graduation minimum: {DEGREE_MINIMUM} credit hours.")
    print("For each plan, paste its standalone DegreeWorks audit.\n")

    cps = ask_number("Typical credits per semester", default=15, minimum=1)
    spy = ask_number("Semesters per year", default=2, minimum=1, integer=True)
    count_in_progress = ask_yes_no(
        "Count in-progress credits as completed?", default=True)
    cost_per_sem = ask_number("Cost per semester ($)", default=20000, minimum=0)

    # Baseline: your one declared major. We read your completed credits here,
    # once, since the cumulative total is the same in every audit.
    major = ask_text("\nYour declared major", default="My major")
    print(f"\n--- {major} (current) ---")
    print(f"  Paste your current audit for: {major}")
    text = read_pasted_audit()
    earned, in_prog = extract_completed(text)
    earned = confirm_or_ask(earned, "credits earned")
    in_prog = confirm_or_ask(in_prog, "credits in progress", default=0)
    completed = earned + (in_prog if count_in_progress else 0)
    floor = max(0.0, DEGREE_MINIMUM - completed)
    print(f"  -> {fmt(completed)} credits completed; {fmt(floor)} to reach "
          f"{DEGREE_MINIMUM}.")

    base_dept, base_need = extract_program_need(text)
    base_need = ask_program_need(base_dept, base_need, major)

    base_remaining, base_driver = remaining_for([base_need], floor)
    scenarios = [{"label": f"{major} (current)", "needs": [base_need],
                  "remaining": base_remaining, "driver": base_driver}]

    # Stack up comparison scenarios.
    while True:
        choice = choose_comparison()
        if choice is None:
            break
        label, n_programs, keep_baseline = choice
        print(f"\n--- {label} ---")
        needs = [base_need] if keep_baseline else []
        for _ in range(n_programs):
            needs.append(collect_program_need(label))
        remaining, driver = remaining_for(needs, floor)
        scenarios.append({"label": label, "needs": needs,
                          "remaining": remaining, "driver": driver})
        print(f"  -> {label}: {fmt(remaining)} credits remaining.")

    print_results(scenarios, cps, spy, cost_per_sem)


if __name__ == "__main__":
    main()
