<!-- Merge term 1 -->
# HPATR System Flowcharts

Paste each code block into [mermaid.live](https://mermaid.live) to render, or view on GitHub.
For Notion: `/code` block → set language to **Mermaid** → paste.

---

## 1 — Experiment Pipeline

```mermaid
flowchart LR

    subgraph CFG["⚙️ Config"]
        YAML["config/paths.yaml"]
        CL["config_loader.py"]
        YAML --> CL
    end

    subgraph HW["📡 Hardware"]
        CAM["Phantom Camera<br/>MP4 @ 1000fps"]
        ARD["Arduino Portenta H7<br/>motor + pressure"]
    end

    subgraph GUI["🖥️ GUI"]
        GC["GUI_Clean.py<br/>PySide6"]
    end

    subgraph CV["🔬 CV Pipeline"]
        M2T["mp4_to_tiff.py<br/>MP4 → TIFF frames<br/>brightest frame"]
        EXP["expansion_detection.py<br/>Canny + Watershed<br/>+ Hough circles"]
        SAA["save_and_analyse.py<br/>entry point"]
        M2T --> EXP
        EXP --> SAA
    end

    subgraph AI["🤖 AI Inference"]
        PR["process_run.py<br/>Dennis Mask R-CNN<br/>droplet + ligament"]
    end

    subgraph OUT["📤 Outputs"]
        O1["{LaCie}/Phantom/<br/>TIFF_Output/"]
        O2["{LaCie}/Shadowgraph/<br/>.../Outputs/<br/>images + CSV"]
        O3["{LaCie}/Shadowgraph/<br/>.../AI_Output/<br/>masks + metrics"]
        O4["{LaCie}/Experiments/<br/>Logs/"]
    end

    CL --> GC
    CL --> M2T
    CL --> SAA
    CL --> PR

    CAM --> GC
    ARD --> GC

    GC --> M2T
    GC --> SAA
    GC --> O4

    M2T --> O1
    M2T --> PR
    SAA --> O2
    PR --> O3
```

---

## 2 — AI Training Pipeline

```mermaid
flowchart LR

    subgraph GEN["🎨 Synthetic Data Generation"]
        SG1["blur_spray_dataset_generator.py"]
        SG2["conjoined_blur_spray_dataset_generator.py"]
    end

    subgraph DATA["📁 Training Data"]
        SYN["AI/synthetic_data/<br/>timestamp/<br/>images + annotations.json"]
        VAL["AI/Validation_100/<br/>blur_annotations.json"]
    end

    subgraph TRAIN["🏋️ Training  Windows"]
        TDT["train_detectron2.py<br/>Mask R-CNN"]
        HPS["hyperparameter_sweep.py<br/>LR + anchor sweep"]
        CVT["convergence_test.py<br/>early stopping"]
    end

    subgraph MODELS["💾 Model Weights"]
        MDL["D:/Experiments/AI/<br/>model_name/<br/>Dennis · Claudia · Benedict"]
    end

    subgraph EVAL["📊 Evaluation"]
        EVM["AI/evaluate_model.py<br/>single model COCO metrics"]
        EVMU["evaluate_multiple_models.py<br/>batch evaluation"]
    end

    subgraph VIZ["📈 Visualisation"]
        V1["extract_sweep_metrics.py"]
        V2["compare_eval_results.py"]
        V3["compare_training_metrics.py"]
        V4["visualize_dennis_vs_claudia.py"]
        V5["plot_from_metrics.py"]
    end

    subgraph OUT["📤 Outputs"]
        O1["local charts + CSVs<br/>training metrics"]
        O2["evaluation_results.xlsx"]
    end

    SG1 --> SYN
    SG2 --> SYN

    SYN --> TDT
    SYN --> HPS
    SYN --> CVT

    TDT --> MDL
    HPS --> MDL
    CVT --> MDL

    MDL --> EVM
    VAL --> EVM
    EVM --> EVMU
    MDL --> EVMU

    EVMU --> O2
    EVM --> V1
    EVM --> V2
    EVMU --> V2
    EVM --> V3
    EVM --> V4
    EVM --> V5

    V1 --> O1
    V2 --> O1
    V3 --> O1
    V4 --> O1
    V5 --> O1
```

---

## 3 — Cone Detection Pipeline

```mermaid
flowchart LR

    subgraph IN["📥 Inputs"]
        WEB["Webcam / Test Images<br/>spray photographs"]
        TIFF["TIFF frames<br/>from CV pipeline"]
    end

    subgraph DETECT["📐 Cone Detection  Trials/"]
        C4["Cone_4.py<br/>PCA-based cone angle<br/>latest algorithm"]
    end

    subgraph TEST["🧪 Testing"]
        CT["Cone_Tester.py<br/>test framework"]
    end

    subgraph UIOUT["🖥️ Interactive"]
        CG["cone_GUI.py<br/>angle display + controls"]
    end

    subgraph OUT["📤 Outputs"]
        O1["cone angle measurements"]
        O2["debug images<br/>cone_4_debug/"]
    end

    WEB --> C4
    TIFF --> C4

    C4 --> CT
    C4 --> CG
    C4 --> O2

    CT --> O1
    CG --> O1
```
