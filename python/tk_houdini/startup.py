import hou

# set the frame range and playbar to the input parameters
def setFrameRange(startFrame, endFrame):
    hou.playbar.setFrameRange(startFrame, endFrame)
    hou.playbar.setPlaybackRange(startFrame, endFrame)
    hou.setFrame(startFrame)