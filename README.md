# AEROPIC dust remover utility (clone stamp)

To have **AEROPIC - dust remover utility** appear directly in your Siril top menu, follow these steps:

### 🚀 Getting Started
1.  **Requirements**: Ensure **Siril 1.2.0+** is installed on your system. Your Python environment must have **sirilpy** installed (this is included by default with the installation of SIRIL).
2.  **Create a Folder**: Create a folder anywhere on your computer (e.g., named `Aeropic`).
3.  **Add the Script**: Place the `AEROPIC_dust_remover_utility.py` file inside this folder.
4.  **Configure Siril**:
    * Open **Siril** and go to the hamburger menu **Preferences**.
    * Navigate to the **Scripts** tab.
    * Add or paste the path to your `Aeropic` folder (link to the **folder**, not the script file itself). (e.g., `C:\Users\ALAIN\AppData\Local\siril-scripts\Aeropic`)
5.  **Restart/Refresh**: After clicking **Apply**, a new entry will appear in your **Scripts menu** containing the tool.

---

## 🖱️ Mouse Controls

* **`ALT` + Left Click**: Defines the **Source** area for the clone stamp (Photoshop style).
* **Left Click (Simple or Drag)**: Applies the stamp to the target area.
* **Right Click (Drag)**: Pans the image within the viewport.

---

## 🛠️ Stamp Modes (Stamp Locked)

### **Unchecked [ ] (Photoshop Mode)**
* The source offset follows the mouse movement after the first click.
* The relative distance between the source and the target is preserved even after releasing the click.
* **To reset or change the origin**: Perform a new `ALT` + Click.

### **Checked [x] (Fixed Source)**
* The source remains strictly locked on the point selected via `ALT` + Click, regardless of where the target moves.

---

## ✨ Interface Features

* **Dynamic Ghost**: A circular preview of actual source pixels appears under the cursor as soon as a source is defined.
* **High Perf Engine**: Optimized for non-GPU systems using NumPy slicing and cached circular masking. (please don't expect a very responsive MMI)
* **Real-time Feedback**: Includes sliders for Diameter, Hardness, Opacity, and Display Stretch.
