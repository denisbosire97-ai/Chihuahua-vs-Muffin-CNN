# Chihuahua vs. Muffin: Neural Network Progression

## 📌 Overview
This repository contains a comprehensive exploration of image classification, navigating from foundational Dense Artificial Neural Networks (ANNs) to advanced Convolutional Neural Networks (CNNs). The core challenge of this project is successfully distinguishing between visually confounding, structurally similar images of Chihuahuas and Blueberry Muffins.

## 🚀 Technologies Used
* **Framework:** TensorFlow / Keras
* **Languages & Tools:** Python 3, Jupyter Notebook, Matplotlib
* **Techniques:** Dense Networks, Convolutional Neural Networks (CNN), Data Augmentation, Dropout, Feature Extraction.

## 📁 Repository Structure
*   **`notebooks/Workshop_1.ipynb`** 
    Implements a baseline Shallow Dense Neural Network. This notebook highlights the mathematical limitations of simple pixel-flattening on complex spatial imagery.
*   **`notebooks/Lab05_CNN_Chihuahua_Muffin.ipynb`** 
    Implements a robust CNN architecture, resolving the translational invariance issues found in the baseline model. It heavily employs `MaxPooling2D`, random data augmentation algorithms (flips/rotations), and `Dropout` layers to severely reduce overfitting and maximize validation accuracy.
*   **`docs/`** 
    Contains deep-dive reflective journals analyzing model performance, the challenges of overfitting on small datasets, ethical considerations in computer vision, and real-world applications.

## 📊 Key Learnings & Observations
*   **Spatial Invariance:** We empirically proved that traditional multi-layer NNs fail on complex, unaligned imagery due to the loss of 2D spatial structures during the flattening phase. The CNN's shared weights and local connectivity proved vastly superior at generalizing from the training set to unseen testing data.
*   **Overfitting Mitigation:** Because the dataset was relatively small and highly specific, the baseline network frequently memorized pixel configurations. Implementing random horizontal flips and zooms in the CNN pipeline artificially expanded the dataset variance, resulting in a much more resilient classifier.
*   **Real-World Application:** The CNN logic deployed in this portfolio forms the exact backbone of modern systems such as autonomous vehicle object detection, facial recognition, and automated manufacturing quality control.
