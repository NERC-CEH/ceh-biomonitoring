# Uploading your survey data to UKCEH

This guide is for partners who collect data with UKCEH's automated monitoring systems, such as AMI light traps, LepiSense units or acoustic recorders, and send it to UKCEH for processing. It explains how to upload your images or sound recordings to the UKCEH data store, step by step. You don't need any programming experience.

If anything goes wrong or you have a question, email **Alyssa Duffy** at [alyduf@ceh.ac.uk](mailto:alyduf@ceh.ac.uk).

## What you need

- **An upload username and password.** UKCEH gives these to partners when it has been agreed that UKCEH will process their data. If you don't have them, email Alyssa Duffy at [alyduf@ceh.ac.uk](mailto:alyduf@ceh.ac.uk).
- **Your survey data**, such as an SD card or a folder on your computer. One upload covers one deployment, so keep each deployment's data in its own folder. Folders inside it are fine; they are searched too.
- **A computer** running Windows, macOS or Linux, with an internet connection.

You set up your computer once (Part 1). After that, every upload is Part 2.

---

## Part 1: Set up (once)

### 1. Install Miniforge

Miniforge is free software that installs Python and the tools the upload needs, without changing anything else on your computer.

1. Go to the [Miniforge download page](https://conda-forge.org/download/) and download the installer for your computer.
   - **Windows:** the Windows installer (`.exe`).
   - **Mac:** pick the one that matches your processor. On newer Macs (M1, M2, M3 and later) it is **arm64 (Apple Silicon)**; on older Macs it is **x86_64 (Intel)**. To check, open the Apple menu and choose **About This Mac**.
2. Run the installer and accept the default options.
   - **Mac or Linux:** open **Terminal** and run the downloaded file, e.g. `bash ~/Downloads/Miniforge3-MacOSX-arm64.sh`, then answer `yes` to the questions.

If your computer is managed by your organisation and blocks installers, ask your IT team to install Miniforge for you.

### 2. Open the Miniforge Prompt

- **Windows:** open the Start menu, search for **Miniforge Prompt** and open it. Use this window for every command in this guide.
- **Mac or Linux:** open **Terminal**. If you had Terminal open during the install, close it and open a new one.

Check it works by typing:

```
conda --version
```

and pressing Enter. You should see `conda` followed by a version number. If you see *"conda is not recognized"*, see [Problems and questions](#problems-and-questions).

### 3. Install the upload tool

Type these three commands, pressing Enter after each one and waiting for it to finish:

```
conda create -n ceh-biomonitoring python=3.11 -y
conda activate ceh-biomonitoring
pip install https://github.com/NERC-CEH/ceh-biomonitoring/archive/refs/heads/main.zip
```

The first one makes a separate space (an "environment") called `ceh-biomonitoring` for the tool, so it doesn't interfere with anything else. The last one downloads and installs the tool. It may take a few minutes.

Check it worked:

```
cehbio --help
```

You should see a list of commands, including `upload`. You're ready.

---

## Part 2: Upload your data (every time)

### 1. Start the upload tool

Open the **Miniforge Prompt** (Windows) or **Terminal** (Mac/Linux) and type:

```
conda activate ceh-biomonitoring
cehbio upload
```

You'll see `(ceh-biomonitoring)` at the start of the line once the environment is active. You don't need to be in any particular folder.

### 2. Answer the questions

The tool asks you, one at a time:

| Question | What to enter |
|---|---|
| **Upload service username** and **password** | The ones UKCEH gave you. The password stays hidden as you type, which is normal. |
| **Your full name** | So we know who sent the data. |
| **Country** | Type the number next to your country. `Test` is only for trying the tool out. |
| **Deployment** | Type the number next to your site and camera or recorder. If yours isn't listed, stop and email us. |
| **What are you uploading?** | `snapshot_images` for trap photos (`.jpg`), `audible_recordings` for normal sound recordings (`.wav`), `ultrasound_recordings` for bat recordings (`.wav`). |
| **Folder with the files** | The folder or SD card with this deployment's data, e.g. `E:\` or `C:\Users\you\Desktop\site1`. |

**Tip for the folder:** on Windows, you can drag the folder from File Explorer into the Miniforge Prompt window to paste its path. On a Mac, drag it into Terminal. Quotation marks around the path are fine.

### 3. Try a test first

The tool asks: **"Try 10 random files first as a test?"** For your first upload of a deployment, type `yes`. It then uploads only 10 files, so you can check everything works before the full upload. Afterwards, run `cehbio upload` again and answer `no` to do the rest; the 10 test files are skipped.

### 4. Check the summary and start

Before uploading, the tool shows a summary:

```
  Name:        Your Name
  Destination: <country> / <deployment> / snapshot_images
  Files:       5321 from E:\
  Log:         ...
```

**Check the number of files.** It should match roughly what you expect from that deployment. If it is much bigger, you may have chosen a folder that contains other data; if it is 0 or very small, see [Problems and questions](#problems-and-questions).

If everything looks right, type `yes` to start. The tool shows its progress as it goes:

- **uploaded:** sent to UKCEH
- **already there:** UKCEH already has this file, so it was skipped
- **failed:** something went wrong with this file (see below)

### 5. When it finishes

The tool tells you how many files were uploaded, skipped and failed. **If any failed, run `cehbio upload` again with the same answers.** Only the files that haven't gone up yet are tried again.

You can close the window when it's finished. Uploading a large deployment can take several hours; keep the computer switched on and connected.

---

## Good to know

- **Your files are never changed, moved or deleted.** The tool only reads them.
- **Interrupted?** If your computer goes to sleep, loses its connection or you close the window, just run `cehbio upload` again with the same answers. It carries on where it left off.
- **Nothing is uploaded twice.** Files already on the UKCEH data store are skipped.
- **What gets uploaded:** for images, `.jpg` files; for sound, `.wav` files. Other files, very small or empty files (under 10 KB) and the recycle bin are ignored. **Zip files are not uploaded**: unzip them first.
- **A record of every upload is kept for you.** Every file is logged in a spreadsheet (`.csv`) in the `ceh-biomonitoring\outputs\upload_logs` folder inside your user folder, e.g. `C:\Users\you\ceh-biomonitoring\outputs\upload_logs`. If you contact us about an upload, it helps to attach this log.
- **Updating the tool:** occasionally we may ask you to update. Run the `pip install ...` command from Part 1, step 3 again, with `conda activate ceh-biomonitoring` first.

---

## Problems and questions

**Some files failed to upload.**
This is usually a short break in the internet connection or the upload service. Run `cehbio upload` again with the same answers; only the failed files are retried. If they still fail a few hours later, email [alyduf@ceh.ac.uk](mailto:alyduf@ceh.ac.uk) and attach the upload log (see [Good to know](#good-to-know)).

**My deployment isn't in the list.**
Don't upload it somewhere else. Email us with the site name and the camera or recorder ID, and we'll add it.

**I uploaded files to the wrong deployment or data type.**
Email [alyduf@ceh.ac.uk](mailto:alyduf@ceh.ac.uk) as soon as you can, saying what you uploaded and where to. We'll move the files to the right place.

**It says "That folder doesn't exist", or it finds far fewer files than I expect.**
- Check the path is complete. Drag the folder into the window to paste it exactly.
- Your computer's security settings may block access to some places, such as some network drives or OneDrive folders that aren't downloaded. Copy the files to a folder on your computer, e.g. on your Desktop, and upload from there.
- Check you chose the right data type: images look for `.jpg` files, recordings for `.wav` files.

**It finds many more files than I expect.**
You've probably chosen a folder that also contains other deployments' data. Choose the folder for just this deployment.

**It says the username or password is wrong.**
Check them carefully; they are case-sensitive. If they still don't work, email us.

**"conda is not recognized as an internal or external command" (Windows).**
You're probably using the ordinary Command Prompt. Use the **Miniforge Prompt** instead: search for it in the Start menu. If there is no Miniforge Prompt, the installation didn't finish: run the installer again, or ask your IT team.

**"cehbio is not recognized" or "command not found".**
The environment isn't active. Type `conda activate ceh-biomonitoring` first. You need to do this every time you open a new window.

**`cehbio` is blocked by my computer's security.**
Some organisations block programs they don't recognise. Use this instead, which does exactly the same:

```
python -m ceh_biomonitoring upload
```

If that is blocked too, ask your IT team, or email us.

**How do I return to the upload tool after closing the window?**
You don't need to set anything up again. Start from [Part 2](#part-2-upload-your-data-every-time).

**How do I remove everything once our survey has finished?**
In the Miniforge Prompt or Terminal, type:

```
conda deactivate
conda env remove -n ceh-biomonitoring
```

Then you can uninstall Miniforge like any other program. Keep the upload logs if you'd like a record of what you sent.

---

## For regular uploaders

You can give all the answers in one command and skip the questions, for example:

```
cehbio upload --name "Your Name" --country "United Kingdom" --deployment "Site name" --data-type snapshot_images --folder E:\ --yes
```

The username and password are still asked for. To avoid typing them each time, set them as the environment variables `CEHBIO_UPLOAD_USER` and `CEHBIO_UPLOAD_PASSWORD`. Only do this on a computer that only you use. `cehbio upload --help` lists every option.
