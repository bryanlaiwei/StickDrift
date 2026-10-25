# StickDrift 3D lobby (Blender)

A playable top-down lobby built and run entirely inside Blender. Walk grandma to a pad and play:

| Pad | Game | Controls |
|---|---|---|
| Game 1 | Apple Picking | left stick = red glove, right stick = blue glove; hover a matching apple, drag it to the basket |
| Game 2 | Harbour Fishing | left stick traces a random shape with the rod, then right stick traces a second one; both fish are caught |
| Game 3 | Rat Catching | flick either stick UP to slam the hand when the rat on the card is under it |

Lobby: left stick walk, right stick orbit/tilt the camera, L1/R1 zoom, Triangle follow/overview, Cross (X) enter a game.
In any game: O (Circle) goes back to the lobby; games return automatically 3 s after the results.

## Run it

Requirements: **Windows**, **Blender 5.x** (built and tested on 5.2 LTS), a PS5/Xbox controller connected.
No add-ons, no Blender MCP and no pip packages are needed - the script only uses Blender's bundled Python.

1. Open Blender and switch to the **Scripting** workspace.
2. Text -> Open -> `legacy/blender_lobby/hub_world.py`, then press **Run Script** (Alt+P). It builds the scene (about a minute) and starts playing.
3. Hover the mouse over the 3D viewport. Esc quits the play loop; run the script again to restart.

Controller input is read through Windows (XInput, falling back to the DirectInput `winmm` API), so it is Windows-only.
