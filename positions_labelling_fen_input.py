#!/usr/bin/env python3

import argparse
import csv
import multiprocessing as mp
import os
import signal
import threading
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED

import chess
import chess.engine


PROGRESS_FILE = "progress.txt"

# ------------------------------------------------------------
# Persistent Stockfish instance per worker
# ------------------------------------------------------------

ENGINE = None
ENGINE_DEPTH = None


# ------------------------------------------------------------
# Worker initializer
# ------------------------------------------------------------

def init_worker(stockfish_path, depth):
    global ENGINE
    global ENGINE_DEPTH

    ENGINE_DEPTH = depth

    ENGINE = chess.engine.SimpleEngine.popen_uci(stockfish_path)


# ------------------------------------------------------------
# Position evaluation
# ------------------------------------------------------------

def evaluate_position(task):

    global ENGINE
    global ENGINE_DEPTH

    line_number, fen = task

    try:
        board = chess.Board(fen)

        info = ENGINE.analyse(
            board,
            chess.engine.Limit(depth=ENGINE_DEPTH)
        )

        score = info["score"].white()

        # Mate score
        if score.is_mate():
            evaluation = f"M{score.mate()}"

        # Centipawn score
        else:
            cp = score.score()

            if cp is None:
                evaluation = ""

            else:
                evaluation = str(cp)

        return (
            line_number,
            fen,
            evaluation,
        )

    except Exception:
        return (
            line_number,
            fen,
            "ERROR",
        )


# ------------------------------------------------------------
# Progress helpers
# ------------------------------------------------------------

def load_progress():

    if not os.path.exists(PROGRESS_FILE):
        return 0

    try:
        with open(PROGRESS_FILE, "r") as f:
            return int(f.read().strip())

    except Exception:
        return 0


def save_progress(last_completed_line):

    tmp = PROGRESS_FILE + ".tmp"

    with open(tmp, "w") as f:
        f.write(str(last_completed_line))

    os.replace(tmp, PROGRESS_FILE)


# ------------------------------------------------------------
# CSV helpers
# ------------------------------------------------------------

def ensure_csv_header(output_csv):

    if os.path.exists(output_csv) and os.path.getsize(output_csv) > 0:
        return

    with open(output_csv, "w", newline="", encoding="utf-8") as f:

        writer = csv.writer(f)

        writer.writerow([
            "fen",
            "evaluation",
        ])


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stockfish", required=True)

    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, mp.cpu_count() - 1),
    )

    parser.add_argument(
        "--depth",
        type=int,
        default=15,
    )

    parser.add_argument(
        "--queue-size",
        type=int,
        default=1000,
    )

    # --------------------------------------------------------
    # Parse arguments
    # --------------------------------------------------------

    args = parser.parse_args()

    # --------------------------------------------------------
    # Validate arguments
    # --------------------------------------------------------

    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file does not exist: {args.input}")

    if not os.path.isfile(args.stockfish):
        errors.append(
            f"Stockfish executable does not exist: {args.stockfish}"
        )

    if args.workers <= 0:
        errors.append("--workers must be greater than 0")

    if args.depth <= 0:
        errors.append("--depth must be greater than 0")

    if args.queue_size <= 0:
        errors.append("--queue-size must be greater than 0")

    if errors:

        print("\nERRORS:\n")

        for err in errors:
            print(f"  - {err}")

        print("\nUsage:\n")

        parser.print_help()

        sys.exit(1)
        
    print("The process can be suspended at any time with Ctrl+C and it will automatically resume next time it is launched")

    ensure_csv_header(args.output)

    start_line = load_progress()

    print(f"Resuming from line: {start_line}")

    stop_event = threading.Event()

    # --------------------------------------------------------
    # Ctrl+C handler
    # --------------------------------------------------------

    def handle_ctrl_c(signum, frame):

        if not stop_event.is_set():

            print("\nCtrl+C received.")
            print("Stopping new submissions...")
            print("Waiting for queued evaluations...")
            stop_event.set()

    signal.signal(signal.SIGINT, handle_ctrl_c)

    pending = set()

    completed_count = 0
    highest_completed_line = start_line

    output_file = open(
        args.output,
        "a",
        newline="",
        encoding="utf-8"
    )

    writer = csv.writer(output_file)

    # --------------------------------------------------------
    # Process pool
    # --------------------------------------------------------

    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=init_worker,
        initargs=(args.stockfish, args.depth),
    ) as executor:

        # ----------------------------------------------------
        # Read input file
        # ----------------------------------------------------

        with open(args.input, "r", encoding="utf-8") as infile:

            for line_number, raw_line in enumerate(infile):

                if line_number < start_line:
                    continue

                if stop_event.is_set():
                    break

                fen = raw_line.strip()

                if not fen:
                    continue

                future = executor.submit(
                    evaluate_position,
                    (line_number, fen),
                )

                pending.add(future)

                # ------------------------------------------------
                # Prevent unbounded queue growth
                # ------------------------------------------------

                while len(pending) >= args.queue_size:

                    done, pending = wait(
                        pending,
                        return_when=FIRST_COMPLETED,
                    )

                    for fut in done:

                        line_no, fen, evaluation = fut.result()

                        writer.writerow([
                            fen,
                            evaluation,
                        ])

                        output_file.flush()

                        highest_completed_line = max(
                            highest_completed_line,
                            line_no + 1,
                        )

                        save_progress(highest_completed_line)

                        completed_count += 1
                    
                        total_processed = highest_completed_line

                        print(
                            f"\rProcessed positions: {total_processed}",
                            end="",
                            flush=True,
                        )

        # ----------------------------------------------------
        # Finish queued evaluations
        # ----------------------------------------------------

        print("\nFinishing queued evaluations...")

        while pending:

            done, pending = wait(
                pending,
                return_when=FIRST_COMPLETED,
            )

            for fut in done:

                try:
                    line_no, fen, evaluation = fut.result()

                    writer.writerow([
                        fen,
                        evaluation,
                    ])

                    output_file.flush()

                    highest_completed_line = max(
                        highest_completed_line,
                        line_no + 1,
                    )

                    save_progress(highest_completed_line)

                    completed_count += 1
                    
                    total_processed = highest_completed_line

                    print(
                        f"\rProcessed positions: {total_processed}",
                        end="",
                        flush=True,
                    )

                except Exception as e:
                    print(f"\nWorker error: {e}")

    output_file.close()

    print("\nDone.")
    print(f"Completed this run: {completed_count}")
    print(f"Resume line saved: {highest_completed_line}")


# ------------------------------------------------------------
# Windows multiprocessing entry point
# ------------------------------------------------------------

if __name__ == "__main__":
    mp.freeze_support()
    main()