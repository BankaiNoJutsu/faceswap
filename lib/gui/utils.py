#!/usr/bin/env python3
""" Utility functions for the GUI """
from dataclasses import dataclass, field
import logging
import os
import platform
import sys
import tkinter as tk

from tkinter import filedialog
from threading import Event, Thread
from typing import (Any, Callable, cast, Dict, IO, List, Optional,
                    Sequence, Tuple, Type, TYPE_CHECKING, Union)
from queue import Queue

import numpy as np

from PIL import Image, ImageDraw, ImageTk

from ._config import Config as UserConfig
from .project import Project, Tasks
from .theme import Style

if sys.version_info < (3, 8):
    from typing_extensions import Literal
else:
    from typing import Literal

if TYPE_CHECKING:
    from types import TracebackType
    from .options import CliOptions
    from .custom_widgets import StatusBar
    from .command import CommandNotebook
    from .command import ToolsNotebook
    from lib.multithreading import _ErrorType


logger = logging.getLogger(__name__)  # pylint: disable=invalid-name
_CONFIG: Optional["Config"] = None
_IMAGES: Optional["Images"] = None
_PREVIEW_TRIGGER: Optional["PreviewTrigger"] = None
PATHCACHE = os.path.join(os.path.realpath(os.path.dirname(sys.argv[0])), "lib", "gui", ".cache")


def initialize_config(root: tk.Tk,
                      cli_opts: "CliOptions",
                      statusbar: "StatusBar") -> Optional["Config"]:
    """ Initialize the GUI Master :class:`Config` and add to global constant.

    This should only be called once on first GUI startup. Future access to :class:`Config`
    should only be executed through :func:`get_config`.

    Parameters
    ----------
    root: :class:`tkinter.Tk`
        The root Tkinter object
    cli_opts: :class:`lib.gui.options.CliOptions`
        The command line options object
    statusbar: :class:`lib.gui.custom_widgets.StatusBar`
        The GUI Status bar

    Returns
    -------
    :class:`Config` or ``None``
        ``None`` if the config has already been initialized otherwise the global configuration
        options
    """
    global _CONFIG  # pylint: disable=global-statement
    if _CONFIG is not None:
        return None
    logger.debug("Initializing config: (root: %s, cli_opts: %s, "
                 "statusbar: %s)", root, cli_opts, statusbar)
    _CONFIG = Config(root, cli_opts, statusbar)
    return _CONFIG


def get_config() -> "Config":
    """ Get the Master GUI configuration.

    Returns
    -------
    :class:`Config`
        The Master GUI Config
    """
    assert _CONFIG is not None
    return _CONFIG


def initialize_images() -> None:
    """ Initialize the :class:`Images` handler  and add to global constant.

    This should only be called once on first GUI startup. Future access to :class:`Images`
    handler should only be executed through :func:`get_images`.
    """
    global _IMAGES  # pylint: disable=global-statement
    if _IMAGES is not None:
        return
    logger.debug("Initializing images")
    _IMAGES = Images()


def get_images() -> "Images":
    """ Get the Master GUI Images handler.

    Returns
    -------
    :class:`Images`
        The Master GUI Images handler
    """
    assert _IMAGES is not None
    return _IMAGES


_FileType = Literal["default", "alignments", "config_project", "config_task",
                    "config_all", "csv", "image", "ini", "state", "log", "video"]
_HandleType = Literal["open", "save", "filename", "filename_multi", "save_filename",
                      "context", "dir"]


class FileHandler():  # pylint:disable=too-few-public-methods
    """ Handles all GUI File Dialog actions and tasks.

    Parameters
    ----------
    handle_type: ['open', 'save', 'filename', 'filename_multi', 'save_filename', 'context', 'dir']
        The type of file dialog to return. `open` and `save` will perform the open and save actions
        and return the file. `filename` returns the filename from an `open` dialog.
        `filename_multi` allows for multi-selection of files and returns a list of files selected.
        `save_filename` returns the filename from a `save as` dialog. `context` is a context
        sensitive parameter that returns a certain dialog based on the current options. `dir` asks
        for a folder location.
    file_type: ['default', 'alignments', 'config_project', 'config_task', 'config_all', 'csv', \
               'image', 'ini', 'state', 'log', 'video']
        The type of file that this dialog is for. `default` allows selection of any files. Other
        options limit the file type selection
    title: str, optional
        The title to display on the file dialog. If `None` then the default title will be used.
        Default: ``None``
    initial_folder: str, optional
        The folder to initially open with the file dialog. If `None` then tkinter will decide.
        Default: ``None``
    initial_file: str, optional
        The filename to set with the file dialog. If `None` then tkinter no initial filename is.
        specified. Default: ``None``
    command: str, optional
        Required for context handling file dialog, otherwise unused. Default: ``None``
    action: str, optional
        Required for context handling file dialog, otherwise unused. Default: ``None``
    variable: str, optional
        Required for context handling file dialog, otherwise unused. The variable to associate
        with this file dialog. Default: ``None``

    Attributes
    ----------
    return_file: str or object
        The return value from the file dialog

    Example
    -------
    >>> handler = FileHandler('filename', 'video', title='Select a video...')
    >>> video_file = handler.return_file
    >>> print(video_file)
    '/path/to/selected/video.mp4'
    """

    def __init__(self,
                 handle_type: _HandleType,
                 file_type: _FileType,
                 title: Optional[str] = None,
                 initial_folder: Optional[str] = None,
                 initial_file: Optional[str] = None,
                 command: Optional[str] = None,
                 action: Optional[str] = None,
                 variable: Optional[str] = None) -> None:
        logger.debug("Initializing %s: (handle_type: '%s', file_type: '%s', title: '%s', "
                     "initial_folder: '%s', initial_file: '%s', command: '%s', action: '%s', "
                     "variable: %s)", self.__class__.__name__, handle_type, file_type, title,
                     initial_folder, initial_file, command, action, variable)
        self._handletype = handle_type
        self._dummy_master = self._set_dummy_master()
        self._defaults = self._set_defaults()
        self._kwargs = self._set_kwargs(title,
                                        initial_folder,
                                        initial_file,
                                        file_type,
                                        command,
                                        action,
                                        variable)
        self.return_file = getattr(self, f"_{self._handletype.lower()}")()
        self._remove_dummy_master()

        logger.debug("Initialized %s", self.__class__.__name__)

    @property
    def _filetypes(self) -> Dict[str, List[Tuple[str, str]]]:
        """ dict: The accepted extensions for each file type for opening/saving """
        all_files = ("All files", "*.*")
        filetypes = dict(
            default=[all_files],
            alignments=[("Faceswap Alignments", "*.fsa"), all_files],
            config_project=[("Faceswap Project files", "*.fsw"), all_files],
            config_task=[("Faceswap Task files", "*.fst"), all_files],
            config_all=[("Faceswap Project and Task files", "*.fst *.fsw"), all_files],
            csv=[("Comma separated values", "*.csv"), all_files],
            image=[("Bitmap", "*.bmp"),
                   ("JPG", "*.jpeg *.jpg"),
                   ("PNG", "*.png"),
                   ("TIFF", "*.tif *.tiff"),
                   all_files],
            ini=[("Faceswap config files", "*.ini"), all_files],
            json=[("JSON file", "*.json"), all_files],
            model=[("Keras model files", "*.h5"), all_files],
            state=[("State files", "*.json"), all_files],
            log=[("Log files", "*.log"), all_files],
            video=[("Audio Video Interleave", "*.avi"),
                   ("Flash Video", "*.flv"),
                   ("Matroska", "*.mkv"),
                   ("MOV", "*.mov"),
                   ("MP4", "*.mp4"),
                   ("MPEG", "*.mpeg *.mpg *.ts *.vob"),
                   ("WebM", "*.webm"),
                   ("Windows Media Video", "*.wmv"),
                   all_files])

        # Add in multi-select options and upper case extensions for Linux
        for key in filetypes:
            if platform.system() == "Linux":
                filetypes[key] = [item
                                  if item[0] == "All files"
                                  else (item[0], f"{item[1]} {item[1].upper()}")
                                  for item in filetypes[key]]
            if len(filetypes[key]) > 2:
                multi = [f"{key.title()} Files"]
                multi.append(" ".join([ftype[1]
                                       for ftype in filetypes[key] if ftype[0] != "All files"]))
                filetypes[key].insert(0, cast(Tuple[str, str], tuple(multi)))
        return filetypes

    @property
    def _contexts(self) -> Dict[str, Dict[str, Union[str, Dict[str, str]]]]:
        """dict: Mapping of commands, actions and their corresponding file dialog for context
        handle types. """
        return dict(effmpeg=dict(input={"extract": "filename",
                                        "gen-vid": "dir",
                                        "get-fps": "filename",
                                        "get-info": "filename",
                                        "mux-audio": "filename",
                                        "rescale": "filename",
                                        "rotate": "filename",
                                        "slice": "filename"},
                                 output={"extract": "dir",
                                         "gen-vid": "save_filename",
                                         "get-fps": "nothing",
                                         "get-info": "nothing",
                                         "mux-audio": "save_filename",
                                         "rescale": "save_filename",
                                         "rotate": "save_filename",
                                         "slice": "save_filename"}))

    @classmethod
    def _set_dummy_master(cls) -> Optional[tk.Frame]:
        """ Add an option to force black font on Linux file dialogs KDE issue that displays light
        font on white background).

        This is a pretty hacky solution, but tkinter does not allow direct editing of file dialogs,
        so we create a dummy frame and add the foreground option there, so that the file dialog can
        inherit the foreground.

        Returns
        -------
        tkinter.Frame or ``None``
            The dummy master frame for Linux systems, otherwise ``None``
        """
        if platform.system().lower() == "linux":
            frame = tk.Frame()
            frame.option_add("*foreground", "black")
            retval: Optional[tk.Frame] = frame
        else:
            retval = None
        return retval

    def _remove_dummy_master(self) -> None:
        """ Destroy the dummy master widget on Linux systems. """
        if platform.system().lower() != "linux" or self._dummy_master is None:
            return
        self._dummy_master.destroy()
        del self._dummy_master
        self._dummy_master = None

    def _set_defaults(self) -> Dict[str, Optional[str]]:
        """ Set the default file type for the file dialog. Generally the first found file type
        will be used, but this is overridden if it is not appropriate.

        Returns
        -------
        dict:
            The default file extension for each file type
        """
        defaults: Dict[str, Optional[str]] = {
            key: next(ext for ext in val[0][1].split(" ")).replace("*", "")
            for key, val in self._filetypes.items()}
        defaults["default"] = None
        defaults["video"] = ".mp4"
        defaults["image"] = ".png"
        logger.debug(defaults)
        return defaults

    def _set_kwargs(self,
                    title: Optional[str],
                    initial_folder: Optional[str],
                    initial_file: Optional[str],
                    file_type: _FileType,
                    command: Optional[str],
                    action: Optional[str],
                    variable: Optional[str] = None
                    ) -> Dict[str, Union[None, tk.Frame, str, List[Tuple[str, str]]]]:
        """ Generate the required kwargs for the requested file dialog browser.

        Parameters
        ----------
        title: str
            The title to display on the file dialog. If `None` then the default title will be used.
        initial_folder: str
            The folder to initially open with the file dialog. If `None` then tkinter will decide.
        initial_file: str
            The filename to set with the file dialog. If `None` then tkinter no initial filename
            is.
        file_type: ['default', 'alignments', 'config_project', 'config_task', 'config_all', \
                    'csv',  'image', 'ini', 'state', 'log', 'video']
            The type of file that this dialog is for. `default` allows selection of any files.
            Other options limit the file type selection
        command: str
            Required for context handling file dialog, otherwise unused.
        action: str
            Required for context handling file dialog, otherwise unused.
        variable: str, optional
            Required for context handling file dialog, otherwise unused. The variable to associate
            with this file dialog. Default: ``None``

        Returns
        -------
        dict:
            The key word arguments for the file dialog to be launched
        """
        logger.debug("Setting Kwargs: (title: %s, initial_folder: %s, initial_file: '%s', "
                     "file_type: '%s', command: '%s': action: '%s', variable: '%s')",
                     title, initial_folder, initial_file, file_type, command, action, variable)

        kwargs: Dict[str, Union[None, tk.Frame, str,
                                List[Tuple[str, str]]]] = dict(master=self._dummy_master)

        if self._handletype.lower() == "context":
            assert command is not None and action is not None and variable is not None
            self._set_context_handletype(command, action, variable)

        if title is not None:
            kwargs["title"] = title

        if initial_folder is not None:
            kwargs["initialdir"] = initial_folder

        if initial_file is not None:
            kwargs["initialfile"] = initial_file

        if self._handletype.lower() in (
                "open", "save", "filename", "filename_multi", "save_filename"):
            kwargs["filetypes"] = self._filetypes[file_type]
            if self._defaults.get(file_type):
                kwargs['defaultextension'] = self._defaults[file_type]
        if self._handletype.lower() == "save":
            kwargs["mode"] = "w"
        if self._handletype.lower() == "open":
            kwargs["mode"] = "r"
        logger.debug("Set Kwargs: %s", kwargs)
        return kwargs

    def _set_context_handletype(self, command: str, action: str, variable: str) -> None:
        """ Sets the correct handle type  based on context.

        Parameters
        ----------
        command: str
            The command that is being executed. Used to look up the context actions
        action: str
            The action that is being performed. Used to look up the correct file dialog
        variable: str
            The variable associated with this file dialog
        """
        if self._contexts[command].get(variable, None) is not None:
            handletype = cast(Dict[str, Dict[str, Dict[str, str]]],
                              self._contexts)[command][variable][action]
        else:
            handletype = cast(Dict[str, Dict[str, str]],
                              self._contexts)[command][action]
        logger.debug(handletype)
        self._handletype = cast(_HandleType, handletype)

    def _open(self) -> Optional[IO]:
        """ Open a file. """
        logger.debug("Popping Open browser")
        return filedialog.askopenfile(**self._kwargs)  # type: ignore

    def _save(self) -> Optional[IO]:
        """ Save a file. """
        logger.debug("Popping Save browser")
        return filedialog.asksaveasfile(**self._kwargs)  # type: ignore

    def _dir(self) -> str:
        """ Get a directory location. """
        logger.debug("Popping Dir browser")
        return filedialog.askdirectory(**self._kwargs)

    def _savedir(self) -> str:
        """ Get a save directory location. """
        logger.debug("Popping SaveDir browser")
        return filedialog.askdirectory(**self._kwargs)

    def _filename(self) -> str:
        """ Get an existing file location. """
        logger.debug("Popping Filename browser")
        return filedialog.askopenfilename(**self._kwargs)

    def _filename_multi(self) -> Tuple[str, ...]:
        """ Get multiple existing file locations. """
        logger.debug("Popping Filename browser")
        return filedialog.askopenfilenames(**self._kwargs)

    def _save_filename(self) -> str:
        """ Get a save file location. """
        logger.debug("Popping Save Filename browser")
        return filedialog.asksaveasfilename(**self._kwargs)

    @staticmethod
    def _nothing() -> None:  # pylint: disable=useless-return
        """ Method that does nothing, used for disabling open/save pop up.  """
        logger.debug("Popping Nothing browser")
        return


class Images():
    """ The centralized image repository for holding all icons and images required by the GUI.

    This class should be initialized on GUI startup through :func:`initialize_images`. Any further
    access to this class should be through :func:`get_images`.
    """
    def __init__(self) -> None:
        logger.debug("Initializing %s", self.__class__.__name__)
        self._pathpreview = os.path.join(PATHCACHE, "preview")
        self._pathoutput: Optional[str] = None
        self._batch_mode = False
        self._previewoutput: Optional[Tuple[Image.Image, ImageTk.PhotoImage]] = None
        self._previewtrain: Dict[str, List[Union[Image.Image,
                                                 ImageTk.PhotoImage,
                                                 None,
                                                 float]]] = {}
        self._previewcache: Dict[str, Union[None, float, np.ndarray, List[str]]] = dict(
            modified=None,  # cache for extract and convert
            images=None,
            filenames=[],
            placeholder=None)
        self._errcount = 0
        self._icons = self._load_icons()
        logger.debug("Initialized %s", self.__class__.__name__)

    @property
    def previewoutput(self) -> Optional[Tuple[Image.Image, ImageTk.PhotoImage]]:
        """ Tuple or ``None``: First item in the tuple is the extract or convert preview image
        (:class:`PIL.Image`), the second item is the image in a format that tkinter can display
        (:class:`PIL.ImageTK.PhotoImage`).

        The value of the property is ``None`` if no extract or convert task is running or there are
        no files available in the output folder. """
        return self._previewoutput

    @property
    def previewtrain(self) -> Dict[str, List[Union[Image.Image, ImageTk.PhotoImage, None, float]]]:
        """ dict or ``None``: The training preview images. Dictionary key is the image name
        (`str`). Dictionary values are a `list` of the training image (:class:`PIL.Image`), the
        image formatted for tkinter display (:class:`PIL.ImageTK.PhotoImage`), the last
        modification time of the image (`float`).

        The value of this property is ``None`` if training is not running or there are no preview
        images available.
        """
        return self._previewtrain

    @property
    def icons(self) -> Dict[str, ImageTk.PhotoImage]:
        """ dict: The faceswap icons for all parts of the GUI. The dictionary key is the icon
        name (`str`) the value is the icon sized and formatted for display
        (:class:`PIL.ImageTK.PhotoImage`).

        Example
        -------
        >>> icons = get_images().icons
        >>> save = icons["save"]
        >>> button = ttk.Button(parent, image=save)
        >>> button.pack()
        """
        return self._icons

    @staticmethod
    def _load_icons() -> Dict[str, ImageTk.PhotoImage]:
        """ Scan the icons cache folder and load the icons into :attr:`icons` for retrieval
        throughout the GUI.

        Returns
        -------
        dict:
            The icons formatted as described in :attr:`icons`

        """
        size = get_config().user_config_dict.get("icon_size", 16)
        size = int(round(size * get_config().scaling_factor))
        icons: Dict[str, ImageTk.PhotoImage] = {}
        pathicons = os.path.join(PATHCACHE, "icons")
        for fname in os.listdir(pathicons):
            name, ext = os.path.splitext(fname)
            if ext != ".png":
                continue
            img = Image.open(os.path.join(pathicons, fname))
            img = ImageTk.PhotoImage(img.resize((size, size), resample=Image.HAMMING))
            icons[name] = img
        logger.debug(icons)
        return icons

    def set_faceswap_output_path(self, location: str, batch_mode: bool = False) -> None:
        """ Set the path that will contain the output from an Extract or Convert task.

        Required so that the GUI can fetch output images to display for return in
        :attr:`previewoutput`.

        Parameters
        ----------
        location: str
            The output location that has been specified for an Extract or Convert task
        batch_mode: bool
            ``True`` if extracting in batch mode otherwise False
        """
        self._pathoutput = location
        self._batch_mode = batch_mode

    def delete_preview(self) -> None:
        """ Delete the preview files in the cache folder and reset the image cache.

        Should be called when terminating tasks, or when Faceswap starts up or shuts down.
        """
        logger.debug("Deleting previews")
        for item in os.listdir(self._pathpreview):
            if item.startswith(".gui_training_preview") and item.endswith(".jpg"):
                fullitem = os.path.join(self._pathpreview, item)
                logger.debug("Deleting: '%s'", fullitem)
                os.remove(fullitem)
        for fname in cast(List[str], self._previewcache["filenames"]):
            if os.path.basename(fname) == ".gui_preview.jpg":
                logger.debug("Deleting: '%s'", fname)
                try:
                    os.remove(fname)
                except FileNotFoundError:
                    logger.debug("File does not exist: %s", fname)
        self._clear_image_cache()

    def _clear_image_cache(self) -> None:
        """ Clear all cached images. """
        logger.debug("Clearing image cache")
        self._pathoutput = None
        self._batch_mode = False
        self._previewoutput = None
        self._previewtrain = {}
        self._previewcache = dict(modified=None,  # cache for extract and convert
                                  images=None,
                                  filenames=[],
                                  placeholder=None)

    @staticmethod
    def _get_images(image_path: str) -> List[str]:
        """ Get the images stored within the given directory.

        Parameters
        ----------
        image_path: str
            The folder containing images to be scanned

        Returns
        -------
        list:
            The image filenames stored within the given folder

        """
        logger.debug("Getting images: '%s'", image_path)
        if not os.path.isdir(image_path):
            logger.debug("Folder does not exist")
            return []
        files = [os.path.join(image_path, f)
                 for f in os.listdir(image_path) if f.lower().endswith((".png", ".jpg"))]
        logger.debug("Image files: %s", files)
        return files

    def load_latest_preview(self, thumbnail_size: int, frame_dims: Tuple[int, int]) -> None:
        """ Load the latest preview image for extract and convert.

        Retrieves the latest preview images from the faceswap output folder, resizes to thumbnails
        and lays out for display. Places the images into :attr:`previewoutput` for loading into
        the display panel.

        Parameters
        ----------
        thumbnail_size: int
            The size of each thumbnail that should be created
        frame_dims: tuple
            The (width (`int`), height (`int`)) of the display panel that will display the preview
        """
        logger.debug("Loading preview image: (thumbnail_size: %s, frame_dims: %s)",
                     thumbnail_size, frame_dims)
        assert self._pathoutput is not None
        image_path = self._get_newest_folder() if self._batch_mode else self._pathoutput
        image_files = self._get_images(image_path)
        gui_preview = os.path.join(self._pathoutput, ".gui_preview.jpg")
        if not image_files or (len(image_files) == 1 and gui_preview not in image_files):
            logger.debug("No preview to display")
            return
        # Filter to just the gui_preview if it exists in folder output
        image_files = [gui_preview] if gui_preview in image_files else image_files
        logger.debug("Image Files: %s", len(image_files))

        image_files = self._get_newest_filenames(image_files)
        if not image_files:
            return

        if not self._load_images_to_cache(image_files, frame_dims, thumbnail_size):
            logger.debug("Failed to load any preview images")
            if gui_preview in image_files:
                # Reset last modified for failed loading of a gui preview image so it is picked
                # up next time
                self._previewcache["modified"] = None
            return

        if image_files == [gui_preview]:
            # Delete the preview image so that the main scripts know to output another
            logger.debug("Deleting preview image")
            os.remove(image_files[0])
        show_image = self._place_previews(frame_dims)
        if not show_image:
            self._previewoutput = None
            return
        logger.debug("Displaying preview: %s", self._previewcache["filenames"])
        self._previewoutput = (show_image, ImageTk.PhotoImage(show_image))

    def _get_newest_folder(self) -> str:
        """ Obtain the most recent folder created in the extraction output folder when processing
        in batch mode.

        Returns
        -------
        str
            The most recently modified folder within the parent output folder. If no folders have
            been created, returns the parent output folder

        """
        assert self._pathoutput is not None
        folders = [os.path.join(self._pathoutput, folder)
                   for folder in os.listdir(self._pathoutput)
                   if os.path.isdir(os.path.join(self._pathoutput, folder))]
        folders.sort(key=os.path.getmtime)
        retval = folders[-1] if folders else self._pathoutput
        logger.debug("sorted folders: %s, return value: %s", folders, retval)
        return retval

    def _get_newest_filenames(self, image_files: List[str]) -> List[str]:
        """ Return image filenames that have been modified since the last check.

        Parameters
        ----------
        image_files: list
            The list of image files to check the modification date for

        Returns
        -------
        list:
            A list of images that have been modified since the last check
        """
        if self._previewcache["modified"] is None:
            retval = image_files
        else:
            retval = [fname for fname in image_files
                      if os.path.getmtime(fname) > cast(float, self._previewcache["modified"])]
        if not retval:
            logger.debug("No new images in output folder")
        else:
            self._previewcache["modified"] = max(os.path.getmtime(img) for img in retval)
            logger.debug("Number new images: %s, Last Modified: %s",
                         len(retval), self._previewcache["modified"])
        return retval

    def _load_images_to_cache(self,
                              image_files: List[str],
                              frame_dims: Tuple[int, int],
                              thumbnail_size: int) -> bool:
        """ Load preview images to the image cache.

        Load new images and append to cache, filtering the cache the number of thumbnails that will
        fit  inside the display panel.

        Parameters
        ----------
        image_files: list
            A list of new image files that have been modified since the last check
        frame_dims: tuple
            The (width (`int`), height (`int`)) of the display panel that will display the preview
        thumbnail_size: int
            The size of each thumbnail that should be created

        Returns
        -------
        bool
            ``True`` if images were successfully loaded to cache otherwise ``False``
        """
        logger.debug("Number image_files: %s, frame_dims: %s, thumbnail_size: %s",
                     len(image_files), frame_dims, thumbnail_size)
        num_images = (frame_dims[0] // thumbnail_size) * (frame_dims[1] // thumbnail_size)
        logger.debug("num_images: %s", num_images)
        if num_images == 0:
            return False
        samples: List[np.ndarray] = []
        start_idx = len(image_files) - num_images if len(image_files) > num_images else 0
        show_files = sorted(image_files, key=os.path.getctime)[start_idx:]
        dropped_files = []
        for fname in show_files:
            try:
                img = Image.open(fname)
            except PermissionError as err:
                logger.debug("Permission error opening preview file: '%s'. Original error: %s",
                             fname, str(err))
                dropped_files.append(fname)
                continue
            except Exception as err:  # pylint:disable=broad-except
                # Swallow any issues with opening an image rather than spamming console
                # Can happen when trying to read partially saved images
                logger.debug("Error opening preview file: '%s'. Original error: %s",
                             fname, str(err))
                dropped_files.append(fname)
                continue

            width, height = img.size
            scaling = thumbnail_size / max(width, height)
            logger.debug("image width: %s, height: %s, scaling: %s", width, height, scaling)

            try:
                img = img.resize((int(width * scaling), int(height * scaling)))
            except OSError as err:
                # Image only gets loaded when we call a method, so may error on partial loads
                logger.debug("OS Error resizing preview image: '%s'. Original error: %s",
                             fname, err)
                dropped_files.append(fname)
                continue

            samples.append(self._pad_and_border(img, thumbnail_size))

        return self._process_samples(samples,
                                     [fname for fname in show_files if fname not in dropped_files],
                                     num_images)

    def _pad_and_border(self, image: Image.Image, size: int) -> np.ndarray:
        """ Pad rectangle images to a square and draw borders

        Parameters
        ----------
        image: :class:`PIL.Image`
            The image to process
        size: int
            The size of the image as it should be displayed

        Returns
        -------
        :class:`PIL.Image`:
            The processed image
        """
        if image.size[0] != image.size[1]:
            # Pad to square
            new_img = Image.new("RGB", (size, size))
            new_img.paste(image, ((size - image.size[0]) // 2, (size - image.size[1]) // 2))
            image = new_img
        draw = ImageDraw.Draw(image)
        draw.rectangle(((0, 0), (size, size)), outline="#E5E5E5", width=1)
        retval = np.array(image)
        logger.trace("image shape: %s", retval.shape)  # type: ignore
        return retval

    def _process_samples(self,
                         samples: List[np.ndarray],
                         filenames: List[str],
                         num_images: int) -> bool:
        """ Process the latest sample images into a displayable image.

        Parameters
        ----------
        samples: list
            The list of extract/convert preview images to display
        filenames: list
            The full path to the filenames corresponding to the images
        num_images: int
            The number of images that should be displayed

        Returns
        -------
        bool
            ``True`` if samples succesfully compiled otherwise ``False``
        """
        asamples = np.array(samples)
        if not np.any(asamples):
            logger.debug("No preview images collected.")
            return False

        self._previewcache["filenames"] = (cast(List[str], self._previewcache["filenames"]) +
                                           filenames)[-num_images:]
        cache = cast(Optional[np.ndarray], self._previewcache["images"])
        if cache is None:
            logger.debug("Creating new cache")
            cache = asamples[-num_images:]
        else:
            logger.debug("Appending to existing cache")
            cache = np.concatenate((cache, asamples))[-num_images:]
        self._previewcache["images"] = cache
        logger.debug("Cache shape: %s", cast(np.ndarray, self._previewcache["images"]).shape)
        return True

    def _place_previews(self, frame_dims: Tuple[int, int]) -> Image.Image:
        """ Format the preview thumbnails stored in the cache into a grid fitting the display
        panel.

        Parameters
        ----------
        frame_dims: tuple
            The (width (`int`), height (`int`)) of the display panel that will display the preview

        Returns
        -------
        :class:`PIL.Image`:
            The final preview display image
        """
        if self._previewcache.get("images", None) is None:
            logger.debug("No images in cache. Returning None")
            return None
        samples = cast(np.ndarray, self._previewcache["images"]).copy()
        num_images, thumbnail_size = samples.shape[:2]
        if self._previewcache["placeholder"] is None:
            self._create_placeholder(thumbnail_size)

        logger.debug("num_images: %s, thumbnail_size: %s", num_images, thumbnail_size)
        cols, rows = frame_dims[0] // thumbnail_size, frame_dims[1] // thumbnail_size
        logger.debug("cols: %s, rows: %s", cols, rows)
        if cols == 0 or rows == 0:
            logger.debug("Cols or Rows is zero. No items to display")
            return None
        remainder = (cols * rows) - num_images
        if remainder != 0:
            logger.debug("Padding sample display. Remainder: %s", remainder)
            placeholder = np.concatenate([np.expand_dims(
                cast(np.ndarray, self._previewcache["placeholder"]), 0)] * remainder)
            samples = np.concatenate((samples, placeholder))

        display = np.vstack([np.hstack(cast(Sequence, samples[row * cols: (row + 1) * cols]))
                             for row in range(rows)])
        logger.debug("display shape: %s", display.shape)
        return Image.fromarray(display)

    def _create_placeholder(self, thumbnail_size: int) -> None:
        """ Create a placeholder image for when there are fewer thumbnails available
        than columns to display them.

        Parameters
        ----------
        thumbnail_size: int
            The size of the thumbnail that the placeholder should replicate
        """
        logger.debug("Creating placeholder. thumbnail_size: %s", thumbnail_size)
        placeholder = Image.new("RGB", (thumbnail_size, thumbnail_size))
        draw = ImageDraw.Draw(placeholder)
        draw.rectangle(((0, 0), (thumbnail_size, thumbnail_size)), outline="#E5E5E5", width=1)
        placeholder = np.array(placeholder)
        self._previewcache["placeholder"] = placeholder
        logger.debug("Created placeholder. shape: %s", placeholder.shape)

    def load_training_preview(self) -> None:
        """ Load the training preview images.

        Reads the training image currently stored in the cache folder and loads them to
        :attr:`previewtrain` for retrieval in the GUI.
        """
        logger.debug("Loading Training preview images")
        image_files = self._get_images(self._pathpreview)
        modified = None
        if not image_files:
            logger.debug("No preview to display")
            self._previewtrain = {}
            return
        for img in image_files:
            modified = os.path.getmtime(img) if modified is None else modified
            name = os.path.basename(img)
            name = os.path.splitext(name)[0]
            name = name[name.rfind("_") + 1:].title()
            try:
                logger.debug("Displaying preview: '%s'", img)
                size = self._get_current_size(name)
                self._previewtrain[name] = [Image.open(img), None, modified]
                self.resize_image(name, size)
                self._errcount = 0
            except ValueError:
                # This is probably an error reading the file whilst it's
                # being saved  so ignore it for now and only pick up if
                # there have been multiple consecutive fails
                logger.warning("Unable to display preview: (image: '%s', attempt: %s)",
                               img, self._errcount)
                if self._errcount < 10:
                    self._errcount += 1
                else:
                    logger.error("Error reading the preview file for '%s'", img)
                    print(f"Error reading the preview file for {name}")
                    del self._previewtrain[name]

    def _get_current_size(self, name: str) -> Optional[Tuple[int, int]]:
        """ Return the size of the currently displayed training preview image.

        Parameters
        ----------
        name: str
            The name of the training image to get the size for

        Returns
        -------
        width: int
            The width of the training image
        height: int
            The height of the training image
        """
        logger.debug("Getting size: '%s'", name)
        if not self._previewtrain.get(name):
            return None
        img = cast(Image.Image, self._previewtrain[name][1])
        if not img:
            return None
        logger.debug("Got size: (name: '%s', width: '%s', height: '%s')",
                     name, img.width(), img.height())
        return img.width(), img.height()

    def resize_image(self, name: str, frame_dims: Optional[Tuple[int, int]]) -> None:
        """ Resize the training preview image based on the passed in frame size.

        If the canvas that holds the preview image changes, update the image size
        to fit the new canvas and refresh :attr:`previewtrain`.

        Parameters
        ----------
        name: str
            The name of the training image to be resized
        frame_dims: tuple, optional
            The (width (`int`), height (`int`)) of the display panel that will display the preview.
            ``None`` if the frame dimensions are not known.
        """
        logger.debug("Resizing image: (name: '%s', frame_dims: %s", name, frame_dims)
        displayimg = cast(Image.Image, self._previewtrain[name][0])
        if frame_dims:
            frameratio = float(frame_dims[0]) / float(frame_dims[1])
            imgratio = float(displayimg.size[0]) / float(displayimg.size[1])

            if frameratio <= imgratio:
                scale = frame_dims[0] / float(displayimg.size[0])
                size = (frame_dims[0], int(displayimg.size[1] * scale))
            else:
                scale = frame_dims[1] / float(displayimg.size[1])
                size = (int(displayimg.size[0] * scale), frame_dims[1])
            logger.debug("Scaling: (scale: %s, size: %s", scale, size)

            # Hacky fix to force a reload if it happens to find corrupted
            # data, probably due to reading the image whilst it is partially
            # saved. If it continues to fail, then eventually raise.
            for i in range(0, 1000):
                try:
                    displayimg = displayimg.resize(size, Image.ANTIALIAS)
                except OSError:
                    if i == 999:
                        raise
                    continue
                break
        self._previewtrain[name][1] = ImageTk.PhotoImage(displayimg)


@dataclass
class _GuiObjects:
    """ Data class for commonly accessed GUI Objects """
    cli_opts: "CliOptions"
    tk_vars: Dict[str, Union[tk.BooleanVar, tk.StringVar]]
    project: Project
    tasks: Tasks
    status_bar: "StatusBar"
    default_options: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    command_notebook: Optional["CommandNotebook"] = None


class Config():
    """ The centralized configuration class for holding items that should be made available to all
    parts of the GUI.

    This class should be initialized on GUI startup through :func:`initialize_config`. Any further
    access to this class should be through :func:`get_config`.

    Parameters
    ----------
    root: :class:`tkinter.Tk`
        The root Tkinter object
    cli_opts: :class:`lib.gui.options.CliOpts`
        The command line options object
    statusbar: :class:`lib.gui.custom_widgets.StatusBar`
        The GUI Status bar
    """
    def __init__(self, root: tk.Tk, cli_opts: "CliOptions", statusbar: "StatusBar") -> None:
        logger.debug("Initializing %s: (root %s, cli_opts: %s, statusbar: %s)",
                     self.__class__.__name__, root, cli_opts, statusbar)
        self._default_font = cast(dict, tk.font.nametofont("TkDefaultFont").configure())["family"]
        self._constants = dict(
            root=root,
            scaling_factor=self._get_scaling(root),
            default_font=self._default_font)
        self._gui_objects = _GuiObjects(
            cli_opts=cli_opts,
            tk_vars=self._set_tk_vars(),
            project=Project(self, FileHandler),
            tasks=Tasks(self, FileHandler),
            status_bar=statusbar)

        self._user_config = UserConfig(None)
        self._style = Style(self.default_font, root, PATHCACHE)
        self._user_theme = self._style.user_theme
        logger.debug("Initialized %s", self.__class__.__name__)

    # Constants
    @property
    def root(self) -> tk.Tk:
        """ :class:`tkinter.Tk`: The root tkinter window. """
        return self._constants["root"]

    @property
    def scaling_factor(self) -> float:
        """ float: The scaling factor for current display. """
        return self._constants["scaling_factor"]

    @property
    def pathcache(self) -> str:
        """ str: The path to the GUI cache folder """
        return PATHCACHE

    # GUI Objects
    @property
    def cli_opts(self) -> "CliOptions":
        """ :class:`lib.gui.options.CliOptions`: The command line options for this GUI Session. """
        return self._gui_objects.cli_opts

    @property
    def tk_vars(self) -> Dict[str, Union[tk.StringVar, tk.BooleanVar]]:
        """ dict: The global tkinter variables. """
        return self._gui_objects.tk_vars

    @property
    def project(self) -> Project:
        """ :class:`lib.gui.project.Project`: The project session handler. """
        return self._gui_objects.project

    @property
    def tasks(self) -> Tasks:
        """ :class:`lib.gui.project.Tasks`: The session tasks handler. """
        return self._gui_objects.tasks

    @property
    def default_options(self) -> Dict[str, Dict[str, Any]]:
        """ dict: The default options for all tabs """
        return self._gui_objects.default_options

    @property
    def statusbar(self) -> "StatusBar":
        """ :class:`lib.gui.custom_widgets.StatusBar`: The GUI StatusBar
        :class:`tkinter.ttk.Frame`. """
        return self._gui_objects.status_bar

    @property
    def command_notebook(self) -> Optional["CommandNotebook"]:
        """ :class:`lib.gui.command.CommandNotebook`: The main Faceswap Command Notebook. """
        return self._gui_objects.command_notebook

    # Convenience GUI Objects
    @property
    def tools_notebook(self) -> "ToolsNotebook":
        """ :class:`lib.gui.command.ToolsNotebook`: The Faceswap Tools sub-Notebook. """
        assert self.command_notebook is not None
        return self.command_notebook.tools_notebook

    @property
    def modified_vars(self) -> Dict[str, "tk.BooleanVar"]:
        """ dict: The command notebook modified tkinter variables. """
        assert self.command_notebook is not None
        return self.command_notebook.modified_vars

    @property
    def _command_tabs(self) -> Dict[str, int]:
        """ dict: Command tab titles with their IDs. """
        assert self.command_notebook is not None
        return self.command_notebook.tab_names

    @property
    def _tools_tabs(self) -> Dict[str, int]:
        """ dict: Tools command tab titles with their IDs. """
        assert self.command_notebook is not None
        return self.command_notebook.tools_tab_names

    # Config
    @property
    def user_config(self) -> UserConfig:
        """ dict: The GUI config in dict form. """
        return self._user_config

    @property
    def user_config_dict(self) -> Dict[str, Any]:  # TODO Dataclass
        """ dict: The GUI config in dict form. """
        return self._user_config.config_dict

    @property
    def user_theme(self) -> Dict[str, Any]:  # TODO Dataclass
        """ dict: The GUI theme selection options. """
        return self._user_theme

    @property
    def default_font(self) -> Tuple[str, int]:
        """ tuple: The selected font as configured in user settings. First item is the font (`str`)
        second item the font size (`int`). """
        font = self.user_config_dict["font"]
        font = self._default_font if font == "default" else font
        return (font, self.user_config_dict["font_size"])

    @staticmethod
    def _get_scaling(root) -> float:
        """ Get the display DPI.

        Returns
        -------
        float:
            The scaling factor
        """
        dpi = root.winfo_fpixels("1i")
        scaling = dpi / 72.0
        logger.debug("dpi: %s, scaling: %s'", dpi, scaling)
        return scaling

    def set_default_options(self) -> None:
        """ Set the default options for :mod:`lib.gui.projects`

        The Default GUI options are stored on Faceswap startup.

        Exposed as the :attr:`_default_opts` for a project cannot be set until after the main
        Command Tabs have been loaded.
        """
        default = self.cli_opts.get_option_values()
        logger.debug(default)
        self._gui_objects.default_options = default
        self.project.set_default_options()

    def set_command_notebook(self, notebook: "CommandNotebook") -> None:
        """ Set the command notebook to the :attr:`command_notebook` attribute
        and enable the modified callback for :attr:`project`.

        Parameters
        ----------
        notebook: :class:`lib.gui.command.CommandNotebook`
            The main command notebook for the Faceswap GUI
        """
        logger.debug("Setting commane notebook: %s", notebook)
        self._gui_objects.command_notebook = notebook
        self.project.set_modified_callback()

    def set_active_tab_by_name(self, name: str) -> None:
        """ Sets the :attr:`command_notebook` or :attr:`tools_notebook` to active based on given
        name.

        Parameters
        ----------
        name: str
            The name of the tab to set active
        """
        assert self.command_notebook is not None
        name = name.lower()
        if name in self._command_tabs:
            tab_id = self._command_tabs[name]
            logger.debug("Setting active tab to: (name: %s, id: %s)", name, tab_id)
            self.command_notebook.select(tab_id)
        elif name in self._tools_tabs:
            self.command_notebook.select(self._command_tabs["tools"])
            tab_id = self._tools_tabs[name]
            logger.debug("Setting active Tools tab to: (name: %s, id: %s)", name, tab_id)
            self.tools_notebook.select()
        else:
            logger.debug("Name couldn't be found. Setting to id 0: %s", name)
            self.command_notebook.select(0)

    def set_modified_true(self, command: str) -> None:
        """ Set the modified variable to ``True`` for the given command in :attr:`modified_vars`.

        Parameters
        ----------
        command: str
            The command to set the modified state to ``True``

        """
        tkvar = self.modified_vars.get(command, None)
        if tkvar is None:
            logger.debug("No tkvar for command: '%s'", command)
            return
        tkvar.set(True)
        logger.debug("Set modified var to True for: '%s'", command)

    def refresh_config(self) -> None:
        """ Reload the user config from file. """
        self._user_config = UserConfig(None)

    def set_cursor_busy(self, widget: Optional[tk.Widget] = None) -> None:
        """ Set the root or widget cursor to busy.

        Parameters
        ----------
        widget: tkinter object, optional
            The widget to set busy cursor for. If the provided value is ``None`` then sets the
            cursor busy for the whole of the GUI. Default: ``None``.
        """
        logger.debug("Setting cursor to busy. widget: %s", widget)
        component = self.root if widget is None else widget
        component.config(cursor="watch")  # type: ignore
        component.update_idletasks()

    def set_cursor_default(self, widget: Optional[tk.Widget] = None) -> None:
        """ Set the root or widget cursor to default.

        Parameters
        ----------
        widget: tkinter object, optional
            The widget to set default cursor for. If the provided value is ``None`` then sets the
            cursor busy for the whole of the GUI. Default: ``None``
        """
        logger.debug("Setting cursor to default. widget: %s", widget)
        component = self.root if widget is None else widget
        component.config(cursor="")  # type: ignore
        component.update_idletasks()

    @staticmethod
    def _set_tk_vars() -> Dict[str, Union[tk.StringVar, tk.BooleanVar]]:
        """ Set the global tkinter variables stored for easy access in :class:`Config`.

        The variables are available through :attr:`tk_vars`.
        """
        display = tk.StringVar()
        display.set("")

        runningtask = tk.BooleanVar()
        runningtask.set(False)

        istraining = tk.BooleanVar()
        istraining.set(False)

        actioncommand = tk.StringVar()
        actioncommand.set("")

        generatecommand = tk.StringVar()
        generatecommand.set("")

        console_clear = tk.BooleanVar()
        console_clear.set(False)

        refreshgraph = tk.BooleanVar()
        refreshgraph.set(False)

        updatepreview = tk.BooleanVar()
        updatepreview.set(False)

        analysis_folder = tk.StringVar()
        analysis_folder.set("")

        tk_vars: Dict[str, Union[tk.StringVar, tk.BooleanVar]] = dict(
            display=display,
            runningtask=runningtask,
            istraining=istraining,
            action=actioncommand,
            generate=generatecommand,
            console_clear=console_clear,
            refreshgraph=refreshgraph,
            updatepreview=updatepreview,
            analysis_folder=analysis_folder)
        logger.debug(tk_vars)
        return tk_vars

    def set_root_title(self, text: Optional[str] = None) -> None:
        """ Set the main title text for Faceswap.

        The title will always begin with 'Faceswap.py'. Additional text can be appended.

        Parameters
        ----------
        text: str, optional
            Additional text to be appended to the GUI title bar. Default: ``None``
        """
        title = "Faceswap.py"
        title += f" - {text}" if text is not None and text else ""
        self.root.title(title)

    def set_geometry(self, width: int, height: int, fullscreen: bool = False) -> None:
        """ Set the geometry for the root tkinter object.

        Parameters
        ----------
        width: int
            The width to set the window to (prior to scaling)
        height: int
            The height to set the window to (prior to scaling)
        fullscreen: bool, optional
            Whether to set the window to full-screen mode. If ``True`` then :attr:`width` and
            :attr:`height` are ignored. Default: ``False``
        """
        self.root.tk.call("tk", "scaling", self.scaling_factor)
        if fullscreen:
            initial_dimensions = (self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        else:
            initial_dimensions = (round(width * self.scaling_factor),
                                  round(height * self.scaling_factor))

        if fullscreen and sys.platform in ("win32", "darwin"):
            self.root.state('zoomed')
        elif fullscreen:
            self.root.attributes('-zoomed', True)
        else:
            self.root.geometry(f"{str(initial_dimensions[0])}x{str(initial_dimensions[1])}+80+80")
        logger.debug("Geometry: %sx%s", *initial_dimensions)


class LongRunningTask(Thread):
    """ Runs long running tasks in a background thread to prevent the GUI from becoming
    unresponsive.

    This is sub-classed from :class:`Threading.Thread` so check documentation there for base
    parameters. Additional parameters listed below.

    Parameters
    ----------
    widget: tkinter object, optional
        The widget that this :class:`LongRunningTask` is associated with. Used for setting the busy
        cursor in the correct location. Default: ``None``.
    """
    _target: Callable
    _args: Tuple
    _kwargs: Dict[str, Any]
    _name: str

    def __init__(self,
                 target: Optional[Callable] = None,
                 name: Optional[str] = None,
                 args: Tuple = (),
                 kwargs: Optional[Dict[str, Any]] = None,
                 *,
                 daemon: bool = True,
                 widget=None):
        logger.debug("Initializing %s: (target: %s, name: %s, args: %s, kwargs: %s, "
                     "daemon: %s)", self.__class__.__name__, target, name, args, kwargs,
                     daemon)
        super().__init__(target=target, name=name, args=args, kwargs=kwargs,
                         daemon=daemon)
        self.err: "_ErrorType" = None
        self._widget = widget
        self._config = get_config()
        self._config.set_cursor_busy(widget=self._widget)
        self._complete = Event()
        self._queue: Queue = Queue()
        logger.debug("Initialized %s", self.__class__.__name__,)

    @property
    def complete(self) -> Event:
        """ :class:`threading.Event`:  Event is set if the thread has completed its task,
        otherwise it is unset.
        """
        return self._complete

    def run(self) -> None:
        """ Commence the given task in a background thread. """
        try:
            if self._target:
                retval = self._target(*self._args, **self._kwargs)
                self._queue.put(retval)
        except Exception:  # pylint: disable=broad-except
            self.err = cast(Tuple[Type[BaseException], BaseException, "TracebackType"],
                            sys.exc_info())
            assert self.err is not None
            logger.debug("Error in thread (%s): %s", self._name,
                         self.err[1].with_traceback(self.err[2]))
        finally:
            self._complete.set()
            # Avoid a ref-cycle if the thread is running a function with
            # an argument that has a member that points to the thread.
            del self._target, self._args, self._kwargs

    def get_result(self) -> Any:
        """ Return the result from the given task.

        Returns
        -------
        varies:
            The result of the thread will depend on the given task. If a call is made to
            :func:`get_result` prior to the thread completing its task then ``None`` will be
            returned
        """
        if not self._complete.is_set():
            logger.warning("Aborting attempt to retrieve result from a LongRunningTask that is "
                           "still running")
            return None
        if self.err:
            logger.debug("Error caught in thread")
            self._config.set_cursor_default(widget=self._widget)
            raise self.err[1].with_traceback(self.err[2])

        logger.debug("Getting result from thread")
        retval = self._queue.get()
        logger.debug("Got result from thread")
        self._config.set_cursor_default(widget=self._widget)
        return retval


class PreviewTrigger():
    """ Triggers to indicate to underlying Faceswap process that the preview image should
    be updated.

    Writes a file to the cache folder that is picked up by the main process.
    """
    def __init__(self) -> None:
        logger.debug("Initializing: %s", self.__class__.__name__)
        self._trigger_files = dict(update=os.path.join(PATHCACHE, ".preview_trigger"),
                                   mask_toggle=os.path.join(PATHCACHE, ".preview_mask_toggle"))
        logger.debug("Initialized: %s (trigger_files: %s)",
                     self.__class__.__name__, self._trigger_files)

    def set(self, trigger_type: Literal["update", "mask_toggle"]):
        """ Place the trigger file into the cache folder

        Parameters
        ----------
        trigger_type: ["update", "mask_toggle"]
            The type of action to trigger. 'update': Full preview update. 'mask_toggle': toggle
            mask on and off
         """
        trigger = self._trigger_files[trigger_type]
        if not os.path.isfile(trigger):
            with open(trigger, "w", encoding="utf8"):
                pass
            logger.debug("Set preview trigger: %s", trigger)

    def clear(self, trigger_type: Optional[Literal["update", "mask_toggle"]] = None) -> None:
        """ Remove the trigger file from the cache folder.

        Parameters
        ----------
        trigger_type: ["update", "mask_toggle", ``None``], optional
            The trigger to clear. 'update': Full preview update. 'mask_toggle': toggle mask on
            and off. ``None`` - clear all triggers. Default: ``None``
        """
        if trigger_type is None:
            triggers = list(self._trigger_files.values())
        else:
            triggers = [self._trigger_files[trigger_type]]
        for trigger in triggers:
            if os.path.isfile(trigger):
                os.remove(trigger)
                logger.debug("Removed preview trigger: %s", trigger)


def preview_trigger() -> PreviewTrigger:
    """ Set the global preview trigger if it has not already been set and return.

    Returns
    -------
    :class:`PreviewTrigger`
        The trigger to indicate to the main faceswap process that it should perform a training
        preview update
    """
    global _PREVIEW_TRIGGER  # pylint:disable=global-statement
    if _PREVIEW_TRIGGER is None:
        _PREVIEW_TRIGGER = PreviewTrigger()
    return _PREVIEW_TRIGGER
