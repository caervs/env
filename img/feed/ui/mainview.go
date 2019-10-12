package ui

import (
	"fmt"
	"os"
	"sort"
	"strings"

	"github.com/jroimartin/gocui"
	"github.com/mmcdole/gofeed"
	"github.com/ulmenhaus/env/img/jql/osm"
	"github.com/ulmenhaus/env/img/jql/storage"
	"github.com/ulmenhaus/env/img/jql/types"
	"github.com/ulmenhaus/env/img/jql/ui"
)

// MainViewMode is the current mode of the MainView.
// It determines which subviews are displayed
type MainViewMode int

const (
	MainViewModeListBar MainViewMode = iota
)

// A MainView is the overall view including a resource list
// and a detailed view of the current resource
type MainView struct {
	OSM *osm.ObjectStoreMapper
	DB  *types.Database

	Mode MainViewMode

	resources [][]types.Entry
	path      string

	breakdown map[string][]Item
}

// NewMainView returns a MainView initialized with a given Table
func NewMainView(path string) (*MainView, error) {
	var store storage.Store
	if strings.HasSuffix(path, ".json") {
		store = &storage.JSONStore{}
	} else {
		return nil, fmt.Errorf("unknown file type")
	}
	mapper, err := osm.NewObjectStoreMapper(store)
	if err != nil {
		return nil, err
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	db, err := mapper.Load(f)
	if err != nil {
		return nil, err
	}
	mv := &MainView{
		OSM: mapper,
		DB:  db,

		path: path,
	}
	// TODO would be good to have a button that can activate
	// the fetch rather than do it automatically at start time
	return mv, mv.fetchResources()
}

type Item struct {
	Link        string
	Description string
}

func (mv *MainView) fetchResources() error {
	// TODO use constants for column names
	// TODO would be good to parallelize fetches
	resourceTable, ok := mv.DB.Tables["resources"]
	if !ok {
		return fmt.Errorf("expected resources table to exist")
	}
	resp, err := resourceTable.Query(types.QueryParams{
		Filters: []types.Filter{
			&ui.EqualFilter{
				Field:     "Feed",
				Col:       2, // XXX hack
				Formatted: "",
				Not:       true,
			},
		},
		OrderBy: "Description",
	})
	if err != nil {
		return err
	}

	/*
		Should only add resources if they're active and have someday or unprocessed
		status. If they have neither and no in progress tasks and no feed, then we also
		add it.
	*/
	mv.resources = resp.Entries
	itemTable, ok := mv.DB.Tables["items"]
	if !ok {
		return fmt.Errorf("expected items table to exist")
	}

	for _, entry := range resp.Entries {
		byDescription := map[string]Item{}
		allItems, err := itemTable.Query(types.QueryParams{
			Filters: []types.Filter{
				&ui.EqualFilter{
					Field:     "Resource",
					Col:       4,                   // XXX
					Formatted: entry[0].Format(""), // XXX
				},
			},
		})
		if err != nil {
			return err
		}
		for _, rawItem := range allItems.Entries {
			byDescription[rawItem[0].Format("")] = Item{ // XXX
				Description: rawItem[0].Format(""), // XXX
				Link:        rawItem[2].Format(""), // XXX
			}
		}

		feed := entry[2].Format("")                                                     // XXX hack
		latest, err := mv.fetchFromFeed(strings.Replace(feed, "rss://", "https://", 1)) // XXX
		if err != nil {
			return err
		}
		for _, item := range latest {
			if _, ok := byDescription[item.Description]; ok {
				continue
			}
			err = itemTable.Insert(item.Description)
			if err != nil {
				return fmt.Errorf("Failed to add entry: %s", err)
			}

			err = itemTable.Update(item.Description, "Link", item.Link)
			if err != nil {
				return fmt.Errorf("Failed to update link for entry: %s", err)
			}

			err = itemTable.Update(item.Description, "Resource", entry[0].Format("")) // XXX
			if err != nil {
				return fmt.Errorf("Failed to update resource for entry: %s", err)
			}
		}
	}
	return nil
}

func (mv *MainView) fetchFromFeed(feedURL string) ([]Item, error) {
	fp := gofeed.NewParser()
	feed, err := fp.ParseURL(feedURL)
	if err != nil {
		return nil, err
	}
	items := make([]Item, len(feed.Items))
	for i, item := range feed.Items {
		items[i] = Item{
			Description: item.Title,
			Link:        item.Link,
		}
	}
	return items, nil
}

// Edit handles keyboard inputs while in table mode
func (mv *MainView) Edit(v *gocui.View, key gocui.Key, ch rune, mod gocui.Modifier) {
	return
}

func (mv *MainView) Layout(g *gocui.Gui) error {
	maxX, maxY := g.Size()
	satisfied, err := g.SetView("Satisfied", maxX/4+1, 0, maxX-1, maxY/4)
	if err != nil && err != gocui.ErrUnknownView {
		return err
	}
	pending, err := g.SetView("Pending", maxX/4+1, maxY/4+1, maxX-1, maxY/2)
	if err != nil && err != gocui.ErrUnknownView {
		return err
	}
	someday, err := g.SetView("Someday", maxX/4+1, maxY/2+1, maxX-1, (3*maxY)/4)
	if err != nil && err != gocui.ErrUnknownView {
		return err
	}
	unprocessed, err := g.SetView("Unprocessed", maxX/4+1, (3*maxY)/4+1, maxX-1, maxY-1)
	if err != nil && err != gocui.ErrUnknownView {
		return err
	}
	resources, err := g.SetView("Resources", 0, 0, maxX/4, maxY-1)
	if err != nil && err == gocui.ErrUnknownView {
		_, err = g.SetCurrentView("Resources")
		if err != nil {
			return err
		}
	} else if err != nil {
		return err
	}
	resources.Clear()
	for _, view := range []*gocui.View{satisfied, pending, someday, unprocessed, resources} {
		view.SelBgColor = gocui.ColorWhite
		view.SelFgColor = gocui.ColorBlack
		view.Highlight = view == g.CurrentView()
		view.Clear()
	}

	for _, entry := range mv.resources {
		fmt.Fprintf(resources, "  %s\n", entry[0].Format(""))
	}
	for status, items := range mv.breakdown {
		for _, item := range items {
			switch status {
			case "Satisfied", "Pending", "Someday", "Unprocessed":
				view, err := g.View(status)
				if err != nil {
					return err
				}
				fmt.Fprintf(view, "  %s\n", item.Description)
			}
		}
	}
	return nil
}

func (mv *MainView) saveContents(g *gocui.Gui, v *gocui.View) error {
	f, err := os.OpenFile(mv.path, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0600)
	if err != nil {
		return err
	}
	defer f.Close()
	err = mv.OSM.Dump(mv.DB, f)
	if err != nil {
		return err
	}
	return nil
}

func (mv *MainView) SetKeyBindings(g *gocui.Gui) error {
	nextMap := map[string]string{
		"Resources":   "Unprocessed",
		"Unprocessed": "Someday",
		"Someday":     "Pending",
		"Pending":     "Satisfied",
		"Satisfied":   "Resources",
	}
	for current, next := range nextMap {
		err := g.SetKeybinding(current, 'n', gocui.ModNone, mv.switcherTo(next))
		if err != nil {
			return err
		}
		err = g.SetKeybinding(next, 'N', gocui.ModNone, mv.switcherTo(current))
		if err != nil {
			return err
		}
		err = g.SetKeybinding(current, 'j', gocui.ModNone, mv.cursorDown)
		if err != nil {
			return err
		}
		err = g.SetKeybinding(current, 'k', gocui.ModNone, mv.cursorUp)
		if err != nil {
			return err
		}
		err = g.SetKeybinding(current, 's', gocui.ModNone, mv.saveContents)
		if err != nil {
			return err
		}

		if current == "Resources" {
			continue
		}
		err = g.SetKeybinding(current, 'J', gocui.ModNone, mv.moveDown)
		if err != nil {
			return err
		}
		err = g.SetKeybinding(current, 'K', gocui.ModNone, mv.moveUp)
		if err != nil {
			return err
		}
	}
	return nil
}

func (mv *MainView) switcherTo(name string) func(g *gocui.Gui, v *gocui.View) error {
	return func(g *gocui.Gui, v *gocui.View) error {
		_, err := g.SetCurrentView(name)
		return err
	}
}

func (mv *MainView) moveDown(g *gocui.Gui, v *gocui.View) error {
	if v == nil {
		return nil
	}
	name := v.Name()
	if name == "Resources" {
		return nil
	}
	_, cy := v.Cursor()
	pk := mv.breakdown[name][cy].Description
	itemTable, ok := mv.DB.Tables["items"]
	if !ok {
		return fmt.Errorf("Expected to find items table")
	}
	new, err := itemTable.Entries[pk][5].Add(-1) // XXX
	if err != nil {
		return err
	}
	itemTable.Entries[pk][5] = new // XXX
	return mv.refreshView(g)
}

func (mv *MainView) moveUp(g *gocui.Gui, v *gocui.View) error {
	if v == nil {
		return nil
	}
	name := v.Name()
	if name == "Resources" {
		return nil
	}
	_, cy := v.Cursor()
	pk := mv.breakdown[name][cy].Description
	itemTable, ok := mv.DB.Tables["items"]
	if !ok {
		return fmt.Errorf("Expected to find items table")
	}
	new, err := itemTable.Entries[pk][5].Add(1) // XXX
	if err != nil {
		return err
	}
	itemTable.Entries[pk][5] = new // XXX
	return mv.refreshView(g)
}

func (mv *MainView) cursorDown(g *gocui.Gui, v *gocui.View) error {
	if v == nil {
		return nil
	}
	cx, cy := v.Cursor()
	if err := v.SetCursor(cx, cy+1); err != nil {
		ox, oy := v.Origin()
		if err := v.SetOrigin(ox, oy+1); err != nil {
			return err
		}
	}
	return mv.refreshView(g)
}

func (mv *MainView) cursorUp(g *gocui.Gui, v *gocui.View) error {
	if v == nil {
		return nil
	}
	ox, oy := v.Origin()
	cx, cy := v.Cursor()
	if err := v.SetCursor(cx, cy-1); err != nil && oy > 0 {
		if err := v.SetOrigin(ox, oy-1); err != nil {
			return err
		}
	}
	return mv.refreshView(g)
}

func (mv *MainView) refreshView(g *gocui.Gui) error {
	itemTable, ok := mv.DB.Tables["items"]
	if !ok {
		return fmt.Errorf("expected items table to exist")
	}
	view, err := g.View("Resources")
	if err != nil {
		return err
	}
	_, cy := view.Cursor()

	entry := mv.resources[cy]

	rawItems, err := itemTable.Query(types.QueryParams{
		Filters: []types.Filter{
			&ui.EqualFilter{
				Field:     "Resource",
				Col:       4,                   // XXX
				Formatted: entry[0].Format(""), // XXX
			},
		},
	})
	if err != nil {
		return err
	}
	mv.breakdown = map[string][]Item{}

	for _, rawItem := range rawItems.Entries {
		status := rawItem[5].Format("") // XXX
		if mv.breakdown[status] == nil {
			mv.breakdown[status] = []Item{}
		}
		mv.breakdown[status] = append(mv.breakdown[status], Item{
			Description: rawItem[0].Format(""), // XXX
			Link:        rawItem[2].Format(""), // XXX
		})
	}
	for _, items := range mv.breakdown {
		sort.Slice(items, func(i, j int) bool {
			return items[i].Description < items[j].Description
		})
	}
	return nil
}
