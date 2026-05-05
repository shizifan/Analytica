// pptxgen_executor.js — long-lived Node bridge for SlideCommand DSL.
//
// Step 0.3 of Sprint 2 closure (see spec/visual_polish_plan.md §4).
//
// Reads a JSON command stream from stdin, replays it onto a pptxgenjs
// presentation, and writes the resulting .pptx bytes to stdout.
//
// Replaces the pre-Step-0 ``generate_pptxgen_script`` path that
// templated JS source per ReportContent. This script is constant —
// extending capability is a Python-side concern (add a new command
// kind in _pptxgen_commands.py + a new ``case`` here).
//
// Coordinate convention: inches, matching Python side.
// Color convention: 6-digit hex without leading '#', matching SOP rules.
//
// Errors are written to stderr and propagated as non-zero exit code.

const pptxgen = require("pptxgenjs");

// ---------------------------------------------------------------------------
// Slide layout — read from CLI args; falls back to 10×7.5 for backward
// compatibility (PR-4: liangang-journal theme passes 13.333×7.5).
// ---------------------------------------------------------------------------

const SLIDE_WIDTH = parseFloat(process.argv[2]) || 10;
const SLIDE_HEIGHT = parseFloat(process.argv[3]) || 7.5;

// ---------------------------------------------------------------------------
// Read full stdin
// ---------------------------------------------------------------------------

async function readStdin() {
    return new Promise((resolve, reject) => {
        let data = "";
        process.stdin.setEncoding("utf-8");
        process.stdin.on("data", (chunk) => { data += chunk; });
        process.stdin.on("end", () => resolve(data));
        process.stdin.on("error", reject);
    });
}

// ---------------------------------------------------------------------------
// Command handlers
// ---------------------------------------------------------------------------

/**
 * Map our internal alignment tokens to pptxgenjs' string values.
 * pptxgenjs accepts "left" | "center" | "right" verbatim; this is here
 * so future renames stay isolated.
 */
function alignmentOf(cmd) {
    return cmd.alignment || "left";
}

function applyNewSlide(pres, cmd) {
    const slide = pres.addSlide();
    if (cmd.background) {
        slide.background = { fill: cmd.background };
    }
    return slide;
}

function applyAddText(slide, cmd) {
    const opts = {
        x: cmd.x, y: cmd.y, w: cmd.w, h: cmd.h,
        fontSize: cmd.font_size,
        bold: !!cmd.bold,
        color: cmd.color,
        align: alignmentOf(cmd),
        valign: "top",
    };
    if (cmd.font_name) opts.fontFace = cmd.font_name;
    slide.addText(cmd.text, opts);
}

// In pptxgenjs 4.x, addChart accepts the lowercase chart type string
// directly. Map our uppercase IR tokens to the library's enum values.
const CHART_TYPE_MAP = {
    BAR: "bar",
    LINE: "line",
    PIE: "pie",
    DOUGHNUT: "doughnut",
};

function applyAddChart(slide, cmd) {
    if (cmd.chart_type === "COMBO") {
        // Multi-type chart: data is an array of {type, data, options}
        // entries. The Node executor unpacks them into the array shape
        // pptxgenjs expects as the first argument of addChart().
        const chartTypes = cmd.data.map((item, idx) => {
            const t = CHART_TYPE_MAP[item.type];
            if (!t) {
                throw new Error(
                    `COMBO entry[${idx}] unknown sub-type: ${item.type}`,
                );
            }
            return {
                type: t,
                data: item.data,
                options: item.options || {},
            };
        });
        slide.addChart(chartTypes, {
            x: cmd.x, y: cmd.y, w: cmd.w, h: cmd.h,
            ...cmd.options,
        });
        return;
    }

    const type = CHART_TYPE_MAP[cmd.chart_type];
    if (!type) {
        throw new Error(`Unknown chart_type: ${cmd.chart_type}`);
    }
    slide.addChart(type, cmd.data, {
        x: cmd.x, y: cmd.y, w: cmd.w, h: cmd.h,
        ...cmd.options,
    });
}

function applyAddTable(slide, cmd) {
    const opts = {
        x: cmd.x, y: cmd.y, w: cmd.w, h: cmd.h,
        ...cmd.options,
    };
    // Cells: convert {text, fill?, color?, bold?, fontSize?, align?} →
    //        pptxgenjs cell options shape.
    const rows = cmd.rows.map(row => row.map(cell => {
        const cellOpts = {};
        if (cell.fill !== undefined) cellOpts.fill = { color: cell.fill };
        if (cell.color !== undefined) cellOpts.color = cell.color;
        if (cell.bold !== undefined) cellOpts.bold = cell.bold;
        if (cell.fontSize !== undefined) cellOpts.fontSize = cell.fontSize;
        if (cell.align !== undefined) cellOpts.align = cell.align;
        return { text: cell.text, options: cellOpts };
    }));
    slide.addTable(rows, opts);
}

function applyAddShape(slide, cmd) {
    // pptxgenjs.ShapeType keys match our enum, but normalise for safety.
    const shapeMap = {
        rect: "rect",
        rounded_rect: "roundRect",
        ellipse: "ellipse",
    };
    const shape = shapeMap[cmd.shape] || "rect";
    const opts = {
        x: cmd.x, y: cmd.y, w: cmd.w, h: cmd.h,
        fill: { color: cmd.fill },
    };
    if (cmd.line_color) {
        opts.line = { color: cmd.line_color };
    }
    // Phase 3.5: rounded-corner radius (Python sends 0.0–1.0; pptxgenjs
    // expects 0–100). Only meaningful for roundRect; harmless on others.
    if (cmd.rect_radius !== undefined && cmd.rect_radius !== null) {
        opts.rectRadius = Math.max(0, Math.min(1, cmd.rect_radius));
    }
    // Phase 3.5: drop shadow (KPI cards, callouts). Theme-friendly default;
    // any future per-shape customisation can extend the IR field.
    if (cmd.shadow) {
        opts.shadow = {
            type: "outer",
            color: "999999",
            opacity: 0.4,
            blur: 8,
            offset: 3,
            angle: 90,
        };
    }
    slide.addShape(shape, opts);
}

function applyAddImage(slide, cmd) {
    slide.addImage({
        x: cmd.x, y: cmd.y, w: cmd.w, h: cmd.h,
        data: cmd.data_uri,
    });
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

async function main() {
    const raw = await readStdin();
    let commands;
    try {
        commands = JSON.parse(raw);
    } catch (e) {
        process.stderr.write(`stdin is not valid JSON: ${e.message}\n`);
        process.exit(2);
    }
    if (!Array.isArray(commands)) {
        process.stderr.write("stdin payload must be a JSON array\n");
        process.exit(2);
    }

    const pres = new pptxgen();
    pres.defineLayout({
        name: "ANALYTICA_WIDE",
        width: SLIDE_WIDTH,
        height: SLIDE_HEIGHT,
    });
    pres.layout = "ANALYTICA_WIDE";

    let currentSlide = null;
    for (let i = 0; i < commands.length; i++) {
        const cmd = commands[i];
        try {
            switch (cmd.type) {
                case "new_slide":
                    currentSlide = applyNewSlide(pres, cmd);
                    break;
                case "add_text":
                    if (!currentSlide) throw new Error("add_text before new_slide");
                    applyAddText(currentSlide, cmd);
                    break;
                case "add_chart":
                    if (!currentSlide) throw new Error("add_chart before new_slide");
                    applyAddChart(currentSlide, cmd);
                    break;
                case "add_table":
                    if (!currentSlide) throw new Error("add_table before new_slide");
                    applyAddTable(currentSlide, cmd);
                    break;
                case "add_shape":
                    if (!currentSlide) throw new Error("add_shape before new_slide");
                    applyAddShape(currentSlide, cmd);
                    break;
                case "add_image":
                    if (!currentSlide) throw new Error("add_image before new_slide");
                    applyAddImage(currentSlide, cmd);
                    break;
                default:
                    throw new Error(`Unknown command type: ${cmd.type}`);
            }
        } catch (e) {
            process.stderr.write(
                `command[${i}] (type=${cmd.type}) failed: ${e.message}\n`,
            );
            process.exit(3);
        }
    }

    let buf;
    try {
        buf = await pres.write({ outputType: "nodebuffer" });
    } catch (e) {
        process.stderr.write(`pres.write failed: ${e.message}\n`);
        process.exit(4);
    }

    // pptxgenjs may return a Buffer or a Uint8Array depending on version
    if (typeof buf === "string") {
        // base64 fallback (older API)
        const decoded = Buffer.from(buf, "base64");
        process.stdout.write(decoded);
    } else {
        process.stdout.write(Buffer.from(buf));
    }
}

main().catch(err => {
    process.stderr.write(`fatal: ${err && err.stack ? err.stack : err}\n`);
    process.exit(1);
});
