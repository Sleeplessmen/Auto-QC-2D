#!/usr/bin/env python3
"""
LetmeQC - Main entry point for Quality Control Tool

Usage:
    python src/main.py <path_to_coco_json> [options]

Examples:
    python src/main.py data/ground_truth/gt_clean_data.json
    python src/main.py data/test_cases/test_poly_errors.json --min-area 50 --iou-threshold 0.85
"""

import argparse
import json
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parser import parse_coco_json
from src.rules import QCRulesEngine


def main():
    parser = argparse.ArgumentParser(
        description="LetmeQC - Quality Control Tool for COCO Format Annotations"
    )
    parser.add_argument(
        "json_path",
        type=str,
        help="Path to COCO format JSON file"
    )
    parser.add_argument(
        "--min-area",
        type=float,
        default=100,
        help="Minimum box area in pixels (default: 100)"
    )
    parser.add_argument(
        "--iou-threshold",
        type=float,
        default=0.95,
        help="IoU threshold for overlap detection (default: 0.95)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file path to save errors as JSON"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output"
    )
    
    args = parser.parse_args()
    
    # Validate input file exists
    if not os.path.exists(args.json_path):
        print(f"Error: File not found: {args.json_path}")
        sys.exit(1)
    
    print(f"Loading data from: {args.json_path}")
    
    # Parse COCO JSON
    try:
        parsed_frames = parse_coco_json(args.json_path)
        print(f"✓ Successfully parsed {len(parsed_frames)} frames")
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        sys.exit(1)
    
    # Run QC checks
    print("\nRunning Quality Control checks...")
    qc_engine = QCRulesEngine(
        min_box_area=args.min_area,
        iou_threshold=args.iou_threshold
    )
    errors = qc_engine.run_qc_check(parsed_frames)
    
    # Output results
    print(f"\n{'='*60}")
    if len(errors) == 0:
        print("✅ PERFECT! No errors found in the dataset.")
    else:
        print(f"❌ FOUND {len(errors)} ERROR(S):")
        print(f"{'='*60}")
        
        for idx, error in enumerate(errors, 1):
            print(f"\nError #{idx}:")
            print(f"  Frame: {error['Frame']}")
            print(f"  Object ID: {error['Object_ID']}")
            print(f"  Type: {error['Error_Type']}")
            print(f"  Message: {error['Message']}")
        
        # Save to file if requested
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(errors, f, indent=4, ensure_ascii=False)
            print(f"\n✓ Errors saved to: {args.output}")
    
    print(f"{'='*60}")
    
    # Return non-zero exit code if errors found
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
